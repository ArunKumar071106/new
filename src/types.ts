export const PERSPECTIVES = ['front', 'back', 'left', 'right', 'top', 'elevated'] as const;
export type Perspective = (typeof PERSPECTIVES)[number];

export const PERSPECTIVE_INFO: Record<Perspective, { label: string; hint: string }> = {
  front: { label: 'Front view', hint: 'Camera facing the front of the object, roughly at its mid-height.' },
  back: { label: 'Back view', hint: 'Opposite side - turn the object (or walk around it) 180 degrees.' },
  left: { label: 'Left view', hint: "The object's own left side (it faces to your left)." },
  right: { label: 'Right view', hint: "The object's own right side (it faces to your right)." },
  top: { label: 'Top view', hint: 'Looking straight down onto the object from above.' },
  elevated: { label: 'Elevated 45 degrees', hint: 'From the front, raised so you look down at about 45 degrees.' },
};

export interface ClientImageStats {
  width: number;
  height: number;
  aspect: number;
  meanLuminance: number;
  sharpness: number;
  warnings: string[];
}

export interface UploadedImage {
  file: File;
  url: string;
  stats?: ClientImageStats;
  error?: string;
}

export type ImageSet = Partial<Record<Perspective, UploadedImage>>;

export interface ViewQuality {
  original_size: [number, number];
  object_area_fraction: number;
  sharpness_laplacian_var: number;
  mean_luminance: number;
  touches_border: boolean;
  mask_source: string;
  warnings: string[];
}

export interface AnalysisResult {
  per_view: Record<Perspective, ViewQuality>;
  same_object: { verdict: string; outliers: string[]; mean_similarity: Record<string, number> };
  overlap: {
    feature_sfm_viable: boolean;
    explanation: string;
    matches_on_object: number;
    matches_on_background: number;
    object_keypoints: Record<string, number>;
  };
  lighting: { white_balance_gains_bgr: Record<string, number[]>; inconsistent: string[] };
  missing_information: string[];
  mask_previews?: Record<string, string>;
}

export interface ReconstructionReport {
  status: string;
  method: string;
  validation: {
    valid: boolean;
    errors: string[];
    vertices: number;
    triangles: number;
    watertight: boolean;
    size_m: { x: number; y: number; z: number };
    texture_mime: string[];
  };
  texture: { observed_surface_fraction: number; inferred_surface_fraction: number };
  consistency: Record<string, { iou: number; mask_explained: number; predicted_outside_mask: number }>;
  poses: {
    turntable: { elevation_deg: number; angles_deg: Record<string, number> };
    free: Record<string, { azimuth_deg: number; elevation_deg: number }>;
    angle_ambiguity: Record<string, { chosen_deg: number; silhouette_plausible_range_deg: [number, number] }>;
  };
  views_used_for_carving: string[];
  views_texture_only: string[];
  base: { mode: string; skirt_height_m: number };
  export: { bytes: number; texture_bytes: number };
  limitations: string[];
  analysis: AnalysisResult;
}

export interface JobStatus {
  id: string;
  state: 'queued' | 'running' | 'done' | 'error';
  progress: number;
  stage: string;
  message: string;
  log: string[];
  error?: string;
  model_url?: string;
  report?: ReconstructionReport;
}

export interface ReconstructionOptions {
  object_height_cm: number;
  bottom_mode: 'flat' | 'hull';
  grid_res: number;
  texture_res: number;
  target_faces: number;
}
