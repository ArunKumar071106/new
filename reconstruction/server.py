"""HTTP API for the reconstruction pipeline (FastAPI).

  GET  /api/health              capability check
  POST /api/analyze             6 images -> segmentation previews + image analysis
  POST /api/reconstruct         6 images + options -> job id (runs in a worker thread)
  GET  /api/jobs/{id}           job status, progress, log, report
  GET  /api/jobs/{id}/model.glb reconstructed model

Successful models are also published to public/models/reconstructed-object.glb
(disable with PUBLISH_TO_PUBLIC=0). If dist/ exists (npm run build) it is served at /.

Run:  .venv/bin/python -m uvicorn reconstruction.server:app --port 8000
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import threading
import traceback
import uuid
from dataclasses import asdict, fields

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from pipeline import Options, run  # noqa: E402
from recon import VIEWS  # noqa: E402
from recon.analysis import analyse  # noqa: E402
from recon.imageio import load_view  # noqa: E402
from recon.segment import complete_mask, segment  # noqa: E402

JOBS_DIR = os.environ.get("JOBS_DIR", os.path.join(HERE, "jobs"))
PUBLIC_MODEL = os.path.join(ROOT, "public", "models", "reconstructed-object.glb")
PUBLISH = os.environ.get("PUBLISH_TO_PUBLIC", "1") != "0"
MAX_BYTES = 30 * 1024 * 1024
ALLOWED = {"image/jpeg", "image/jpg", "image/png", "image/webp", "application/octet-stream"}

app = FastAPI(title="3D Reconstruction API")
jobs: dict[str, dict] = {}
cpu_lock = threading.Lock()  # one CPU-heavy task at a time


def _segmentation_backend() -> str:
    try:
        import rembg  # noqa: F401

        return "rembg/u2net"
    except Exception:
        return "grabcut-fallback"


@app.get("/api/health")
def health():
    return {"ok": True, "segmentation": _segmentation_backend(), "busy": cpu_lock.locked()}


async def _save_uploads(request: Request, dest: str) -> tuple[dict[str, str], dict]:
    form = await request.form()
    os.makedirs(dest, exist_ok=True)
    paths = {}
    missing = [v for v in VIEWS if v not in form]
    if missing:
        raise HTTPException(400, f"Missing perspectives: {', '.join(missing)}")
    for v in VIEWS:
        up = form[v]
        if not hasattr(up, "read"):
            raise HTTPException(400, f"{v}: expected a file upload")
        if up.content_type not in ALLOWED:
            raise HTTPException(415, f"{v}: unsupported type {up.content_type}; use JPEG, PNG or WebP")
        data = await up.read()
        if len(data) > MAX_BYTES:
            raise HTTPException(413, f"{v}: file larger than 30 MB")
        if cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_REDUCED_GRAYSCALE_8) is None:
            raise HTTPException(400, f"{v}: file is not a decodable image")
        ext = os.path.splitext(up.filename or "")[1].lower() or ".img"
        p = os.path.join(dest, f"{v}{ext}")
        with open(p, "wb") as fh:
            fh.write(data)
        paths[v] = p
    opts = {}
    if "options" in form:
        try:
            raw = json.loads(str(form["options"]))
            valid = {f.name for f in fields(Options)}
            opts = {k: v for k, v in raw.items() if k in valid}
        except json.JSONDecodeError:
            raise HTTPException(400, "options must be JSON")
    return paths, opts


def _mask_overlay(view) -> str:
    """Transparent PNG: green outline + light tint of the segmented object (for UI previews)."""
    m = view.mask
    h, w = m.shape
    s = 640 / max(h, w)
    m = cv2.resize(m, (round(w * s), round(h * s)), interpolation=cv2.INTER_NEAREST)
    rgba = np.zeros((*m.shape, 4), np.uint8)
    rgba[m > 0] = (34, 197, 94, 40)
    cnt, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(rgba, cnt, -1, (34, 197, 94, 255), 3)
    ok, buf = cv2.imencode(".png", cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
    return "data:image/png;base64," + base64.b64encode(buf).decode()


@app.post("/api/analyze")
async def analyze(request: Request):
    tmp = os.path.join(JOBS_DIR, "analyze-" + uuid.uuid4().hex[:8])
    paths, _ = await _save_uploads(request, tmp)

    def work():
        views = {n: load_view(n, paths[n]) for n in VIEWS}
        for v in views.values():
            m, src = segment(v.work)
            m2 = complete_mask(v.work, m)
            gain = m2.sum() / max(m.sum(), 1) - 1
            v.mask, v.mask_source = m2, src
            v.meta["completion_gain"] = float(gain)
        rep = analyse(views)
        for n, v in views.items():
            if v.meta["completion_gain"] > 0.10:
                rep["per_view"][n]["warnings"].append(
                    f"segmentation missed ~{v.meta['completion_gain'] * 100:.0f}% of the object; recovered by colour completion")
        rep["mask_previews"] = {n: _mask_overlay(v) for n, v in views.items()}
        return rep

    try:
        with cpu_lock:
            from starlette.concurrency import run_in_threadpool

            rep = await run_in_threadpool(work)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    from pipeline import _jsonable

    return _jsonable(rep)


@app.post("/api/reconstruct")
async def reconstruct(request: Request):
    jid = uuid.uuid4().hex[:12]
    jdir = os.path.join(JOBS_DIR, jid)
    paths, opts = await _save_uploads(request, os.path.join(jdir, "input"))
    job = {"id": jid, "state": "queued", "progress": 0.0, "stage": "queued", "message": "Waiting for the CPU...",
           "log": [], "dir": jdir}
    jobs[jid] = job

    def progress(frac, stage, msg):
        job.update(progress=float(frac), stage=stage, message=msg)

    def worker():
        with cpu_lock:
            job.update(state="running", stage="starting", message="")
            out = os.path.join(jdir, "model.glb")
            try:
                o = Options(**{**asdict(Options()), **opts})
                import builtins

                orig_print = builtins.print

                def tee(*a, **k):  # capture the pipeline log for the UI
                    job["log"].append(" ".join(str(x) for x in a))
                    orig_print(*a, **k)

                builtins.print = tee
                try:
                    rep = run(paths, out, os.path.join(jdir, "report.json"), o, progress_cb=progress)
                finally:
                    builtins.print = orig_print
                if rep["status"] != "ok":
                    raise RuntimeError("exported GLB failed validation: " + ", ".join(rep["validation"]["errors"]))
                if PUBLISH:
                    os.makedirs(os.path.dirname(PUBLIC_MODEL), exist_ok=True)
                    shutil.copyfile(out, PUBLIC_MODEL)
                    shutil.copyfile(os.path.join(jdir, "report.json"),
                                    os.path.splitext(PUBLIC_MODEL)[0] + ".report.json")
                rep.pop("log", None)
                job.update(state="done", progress=1.0, stage="done", message="Model ready",
                           model_url=f"/api/jobs/{jid}/model.glb", report=rep)
            except Exception as exc:  # report every failure to the UI
                traceback.print_exc()
                job.update(state="error", stage="failed", error=f"{type(exc).__name__}: {exc}")

    threading.Thread(target=worker, daemon=True).start()
    return {"id": jid}


@app.get("/api/jobs/{jid}")
def job_status(jid: str):
    job = jobs.get(jid)
    if not job:
        raise HTTPException(404, "unknown job")
    return {k: v for k, v in job.items() if k != "dir"}


@app.get("/api/jobs/{jid}/model.glb")
def job_model(jid: str):
    job = jobs.get(jid)
    if not job or job["state"] != "done":
        raise HTTPException(404, "model not ready")
    return FileResponse(os.path.join(job["dir"], "model.glb"), media_type="model/gltf-binary",
                        filename="reconstructed-object.glb")


_dist = os.path.join(ROOT, "dist")
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="static")
