"""Build the 3D model of the 250 g "Ribbon Seeval" snack bag.

usage:  python build.py [--quick] [--out ../output/snack_bag/ribbon_seeval_bag.glb]
"""
import argparse
import json
import os
import sys
import time
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "reconstruction"))
import geom as G                                   # noqa: E402
from gltf_writer import GLBWriter                  # noqa: E402
import bag                                         # noqa: E402
from snack import Piece, snack_textures            # noqa: E402

T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:6.1f}s]", *a, flush=True)


def pack_pieces(shape, pieces, window_pts, window_nrm, target, rng):
    """Random packing with collision rejection. Most pieces sit just behind
    the clear film (that is what can be seen); some fill the interior."""
    placed, cloud = [], []
    tree = None
    trials = 0
    while len(placed) < target and trials < target * 60:
        trials += 1
        p = pieces[int(rng.integers(len(pieces)))]
        sc = rng.uniform(0.92, 1.08)
        if rng.random() < 0.78:
            k = int(rng.integers(len(window_pts)))
            nrm = -window_nrm[k]                         # inward
            c = window_pts[k] + nrm * rng.uniform(2.5, 9.0)
            # orient the ribbon roughly parallel to the film, random spin + tilt
            spin = Rotation.from_rotvec(np.array([0, 0, 1.0]) * rng.uniform(0, 2 * np.pi))
            tilt = Rotation.from_rotvec(rng.normal(0, 0.55, 3))
            z = np.array([0, 0, 1.0])
            ax = np.cross(z, nrm)
            if np.linalg.norm(ax) < 1e-6:
                align = Rotation.identity()
            else:
                align = Rotation.from_rotvec(ax / np.linalg.norm(ax) * np.arccos(np.clip(z @ nrm, -1, 1)))
            R = tilt * align * spin
        else:
            c = np.array([rng.uniform(-50, 50), rng.uniform(8, 100), rng.uniform(-30, 30)])
            R = Rotation.random(random_state=int(rng.integers(1 << 30)))
        pts = R.apply(p.samples * sc) + c
        if (shape.inside_sdf(pts) > -1.1).any():
            continue
        if tree is not None:
            d, _ = tree.query(pts)
            if (d < 0.9).mean() > 0.03:
                continue
        placed.append((p.idx, c, R.as_quat(), sc))
        cloud.append(pts)
        if len(placed) % 10 == 0 or tree is None:
            tree = cKDTree(np.concatenate(cloud))
        else:
            tree = cKDTree(np.concatenate(cloud))
    return placed, trials


def thread_mesh():
    """Yellow cotton thread: three tight turns round the neck + two tails."""
    rr, r_th = bag.R_NECK + 1.15, 0.5
    turns = 3.0
    s = np.linspace(0, 1, 420)
    ang = s * turns * 2 * np.pi
    y = bag.HT - 0.5 + 3.2 * s + 0.25 * np.sin(ang * 3.0)
    path = np.stack([rr * np.sin(ang), y, rr * np.cos(ang)], 1)
    # tails: leave the knot tangentially and droop a little
    def tail(p0, d, n=40, L=9.0):
        t = np.linspace(0, 1, n)[1:, None]
        return p0 + d * L * t + np.array([0, -2.5, 0]) * t ** 2
    d_end = path[-1] - path[-2]; d_end /= np.linalg.norm(d_end)
    d_sta = path[0] - path[1]; d_sta /= np.linalg.norm(d_sta)
    path = np.concatenate([tail(path[0], d_sta)[::-1], path, tail(path[-1], d_end)])
    T = np.gradient(path, axis=0); T /= np.linalg.norm(T, axis=1, keepdims=True)
    Nn = np.cross(T, [0, 1, 0]); Nn /= np.linalg.norm(Nn, axis=1, keepdims=True) + 1e-9
    Bn = np.cross(T, Nn)
    nseg = 10
    a = np.linspace(0, 2 * np.pi, nseg + 1)
    ring = (np.cos(a)[None, :, None] * Nn[:, None, :] + np.sin(a)[None, :, None] * Bn[:, None, :])
    V = (path[:, None, :] + r_th * ring).reshape(-1, 3)
    N = ring.reshape(-1, 3)
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))])
    UV = np.stack(np.meshgrid(a / (2 * np.pi), arc / 4.0)[::-1], -1)[..., ::-1].reshape(-1, 2)
    UV = np.stack([np.repeat(arc / 4.0, nseg + 1), np.tile(a / (2 * np.pi), len(path))], 1)
    nr, nc = len(path), nseg + 1
    idx = np.arange(nr * nc).reshape(nr, nc)
    q0, q1, q2, q3 = idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()
    F = np.concatenate([np.stack([q0, q1, q2], 1), np.stack([q0, q2, q3], 1)])
    # end caps
    caps = []
    for end, flip in ((0, True), (nr - 1, False)):
        c_i = len(V) + len(caps)
        caps.append(path[end])
    Vc = np.concatenate([V, np.array(caps)])
    Nc = np.concatenate([N, np.array([-T[0], T[-1]])])
    UVc = np.concatenate([UV, np.zeros((2, 2))])
    extra = []
    for k, (end, cidx) in enumerate(((0, len(V)), (nr - 1, len(V) + 1))):
        for j in range(nseg):
            a_, b_ = idx[end, j], idx[end, j + 1]
            extra.append([cidx, b_, a_] if end == 0 else [cidx, a_, b_])
    F = np.concatenate([F, np.array(extra)])
    vol = np.einsum("ij,ij->i", Vc[F[:, 0]], np.cross(Vc[F[:, 1]], Vc[F[:, 2]])).sum()
    if vol < 0:
        F = F[:, ::-1]
    return Vc, Nc, UVc, F


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default=os.path.join(HERE, "..", "output", "snack_bag", "ribbon_seeval_bag.glb"))
    args = ap.parse_args()
    q = args.quick
    rng = np.random.default_rng(2024)
    stats = {}
    W = GLBWriter()

    # ------------------------------------------------ bag film
    shape = bag.BagShape()
    V, UV, F, (nr, nc) = shape.mesh(nu=160 if q else 300, nt=120 if q else 220)
    N = G.vertex_normals(V, F)
    Ng = N.reshape(nr, nc, 3)
    Ng[:, 0] = Ng[:, -1] = G.nrm(Ng[:, 0] + Ng[:, -1])           # no shading seam
    Ng[0] = [0, -1, 0]
    N = Ng.reshape(-1, 3)
    TAN = G.tangents(V, N, UV, F)
    log("bag film", len(F), "tris; building print atlas")
    ru, rv = (2048, 1024) if q else (4096, 2048)
    col, win = bag.print_atlas(shape, ru, rv)
    alb = col * (1 - win[..., None]) + np.array([0.97, 0.97, 0.965]) * win[..., None]
    trans = (np.clip(win, 0, 1) * 0.93 * 255).astype(np.uint8)
    hn = bag.film_normal(1024 if q else 2048, 512 if q else 1024)
    fnorm = G.normal_map_from_height_image(hn, 0.9)
    m_film = W.material("BagFilm_PrintedPP", base=W.texture(alb, quality=92, key="film_albedo"),
                        normal=W.texture(fnorm, quality=90), normal_scale=0.8, rough=0.07, metal=0.0,
                        double_sided=True,
                        transmission={"transmissionFactor": 1.0,
                                      "transmissionTexture": {"index": W.texture(trans, kind="png", key="film_window")}},
                        ior=1.49)
    bag_node = W.node("Bag_Film", W.mesh_only("Bag_Film", [dict(V=V, N=N, UV=UV, TAN=TAN, F=F, material=m_film)]))
    stats["bag_film_tris"] = int(len(F))

    # ------------------------------------------------ thread
    tV, tN, tUV, tF = thread_mesh()
    tt = 256
    uu, vv = np.meshgrid(np.arange(tt) / tt, np.arange(tt) / tt)
    ply = 0.5 + 0.5 * np.sin(2 * np.pi * (uu * 3 + vv * 2))
    t_alb = np.stack([0.86 + 0.06 * ply, 0.86 + 0.05 * ply, 0.28 + 0.05 * ply], -1)
    m_thr = W.material("Thread_YellowCotton", base=W.texture(np.clip(t_alb, 0, 1), quality=90),
                       normal=W.texture(G.normal_map_from_height_image(ply, 2.0), quality=90), rough=0.9,
                       sheen={"sheenColorFactor": [0.9, 0.9, 0.5], "sheenRoughnessFactor": 0.5})
    tTAN = G.tangents(tV, tN, tUV, tF)
    thr_node = W.node("Thread", W.mesh_only("Thread", [dict(V=tV, N=tN, UV=tUV, TAN=tTAN, F=tF, material=m_thr)]))
    stats["thread_tris"] = int(len(tF))

    # ------------------------------------------------ snack pieces
    pieces = [Piece(i, rng).build() for i in range(17)]
    log("snack pieces built; baking food textures")
    res = 1024 if q else 4096
    s_alb, s_h, s_r, s_ao, pxmm = snack_textures(pieces, res=res)
    s_nrm = G.normal_map_from_height_image(s_h, pxmm)
    small = (lambda a: a[::2, ::2]) if not q else (lambda a: a)
    m_snk = W.material("RibbonSeeval_FriedDough",
                       base=W.texture(s_alb, quality=90),
                       normal=W.texture(small(s_nrm), quality=90),
                       orm=W.texture(small(np.stack([s_ao, s_r, np.zeros_like(s_r)], -1)), quality=90))
    piece_mesh = []
    for p in pieces:
        pN = G.vertex_normals(p.V, p.F)
        pT = G.tangents(p.V, pN, p.UV, p.F)
        piece_mesh.append(W.mesh_only(f"RibbonSeeval_piece_{p.idx:02d}",
                                      [dict(V=p.V, N=pN, UV=p.UV, TAN=pT, F=p.F, material=m_snk)]))
    # where the film is clear (and below the tie) the contents are visible
    wv = (UV[:, 1] * (rv - 1)).astype(int).clip(0, rv - 1)
    wu = (UV[:, 0] * (ru - 1)).astype(int).clip(0, ru - 1)
    clear = (win[wv, wu] > 0.5) & (V[:, 1] > 6) & (V[:, 1] < bag.HT - 12)
    wp, wn = V[clear], N[clear]
    log("packing; visible-window wall points:", len(wp))
    placed, trials = pack_pieces(shape, pieces, wp, wn, 70 if q else 210, rng)
    log(f"placed {len(placed)} pieces in {trials} trials")
    snack_nodes = [W.node(f"piece_{i:03d}", piece_mesh[pi], translation=c, rotation=quat, scale=[s, s, s])
                   for i, (pi, c, quat, s) in enumerate(placed)]
    snacks_group = len(W.j["nodes"])
    W.j["nodes"].append({"name": "RibbonSeeval_Pieces", "children": snack_nodes})
    W.group("RibbonSeevalBag_250g", [bag_node, thr_node, snacks_group])
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    size = W.write(args.out)
    stats.update({
        "file_bytes": size,
        "unique_piece_meshes": len(pieces),
        "piece_instances": len(placed),
        "triangles_stored": int(stats["bag_film_tris"] + stats["thread_tris"] + sum(len(p.F) for p in pieces)),
        "triangles_drawn": int(stats["bag_film_tris"] + stats["thread_tris"] + sum(len(pieces[pi].F) for pi, *_ in placed)),
        "textures": {"film_print": f"{ru}x{rv}", "film_window_mask": f"{ru}x{rv}", "film_normal": f"{hn.shape[1]}x{hn.shape[0]}",
                     "snack_albedo": f"{res}x{res}", "snack_normal_orm": f"{res // (1 if q else 2)}x{res // (1 if q else 2)}",
                     "thread": "256x256"},
        "dimensions_mm": {"body_width": bag.W, "body_depth": bag.D, "tie_height": bag.HT, "top_height": bag.HR},
    })
    with open(os.path.splitext(args.out)[0] + "_stats.json", "w") as f:
        json.dump(stats, f, indent=2)
    log(f"wrote {args.out}: {size / 1e6:.2f} MB; drawn tris {stats['triangles_drawn']}")


if __name__ == "__main__":
    main()
