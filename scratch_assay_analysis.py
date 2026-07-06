#!/usr/bin/env python3

from pathlib import Path
import argparse
import os
import re
import tempfile

import cv2
import numpy as np
import pandas as pd
_cache_dir = Path(tempfile.gettempdir()) / "scratch_assay_cache"
_cache_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(_cache_dir / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(_cache_dir))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

TIMEPOINT_RE = r'\b(\d+)\s*(hrs|hr|hours|hour|h)(?=$|[^A-Za-z0-9])'
FIELD_ID_RE = r'(?<![A-Za-z0-9])([A-H]\d{2}f\d{2}d\d+)(?![A-Za-z0-9])'
GENERIC_FOLDER_NAMES = {
    "images",
    "image",
    "scratch",
    "scratch_assay",
    "scratch_assays",
    "wound",
    "wound_healing",
    "timepoint",
    "time_point",
}
GENERIC_FILE_GROUPS = {"image", "img", "field", "scan", "tile", "well"}


# =========================================================
# Utilities
# =========================================================

def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_gray(image_path: Path) -> np.ndarray:
    img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Could not load image: {image_path}")
    return img


def moving_average_1d(arr: np.ndarray, window: int) -> np.ndarray:
    if window < 1:
        return arr.copy()
    if window % 2 == 0:
        window += 1
    kernel = np.ones(window, dtype=float) / window
    return np.convolve(arr, kernel, mode="same")


def normalize_0_1(arr: np.ndarray) -> np.ndarray:
    arr = arr.astype(np.float32)
    mn = float(np.min(arr))
    mx = float(np.max(arr))
    if mx - mn < 1e-12:
        return np.zeros_like(arr, dtype=np.float32)
    return (arr - mn) / (mx - mn)


def most_common_nonnull(df: pd.DataFrame, column: str, default):
    if column not in df.columns:
        return default
    vals = df[column].dropna()
    if vals.empty:
        return default
    return vals.astype(str).mode().iloc[0]


def contiguous_true_runs(mask_1d: np.ndarray):
    runs = []
    in_run = False
    start = 0
    for i, val in enumerate(mask_1d):
        if val and not in_run:
            start = i
            in_run = True
        elif not val and in_run:
            runs.append((start, i - 1))
            in_run = False
    if in_run:
        runs.append((start, len(mask_1d) - 1))
    return runs


def parse_filename_metadata(filename: str) -> dict:
    stem = Path(filename).stem
    clean_stem = re.sub(r'\s+copy(?:\s+\d+)?$', '', stem, flags=re.IGNORECASE).strip()

    meta = {
        "filename": filename,
        "stem": clean_stem,
        "time_raw": None,
        "time_value": None,
        "time_unit": None,
        "well_id": None,
        "field_id": None,
        "condition_id": None,
        "group_id": None,
    }

    time_match = re.search(TIMEPOINT_RE, clean_stem, flags=re.IGNORECASE)
    if time_match:
        meta["time_raw"] = time_match.group(0)
        meta["time_value"] = int(time_match.group(1))
        meta["time_unit"] = "h"

    field_match = re.search(FIELD_ID_RE, clean_stem, flags=re.IGNORECASE)
    if field_match:
        meta["field_id"] = field_match.group(1).upper()
        well_match = re.match(r'([A-H])(\d{2})', meta["field_id"], flags=re.IGNORECASE)
        if well_match:
            meta["well_id"] = f"{well_match.group(1).upper()}{int(well_match.group(2))}"

    without_time = re.sub(TIMEPOINT_RE, '', clean_stem, flags=re.IGNORECASE)
    well_match = re.search(r'\b([A-H])0?(\d{1,2})\b', without_time, flags=re.IGNORECASE)
    if well_match:
        explicit_well = f"{well_match.group(1).upper()}{int(well_match.group(2))}"
        meta["well_id"] = meta["well_id"] or explicit_well

    group_stem = clean_stem
    group_stem = re.sub(TIMEPOINT_RE, '', group_stem, flags=re.IGNORECASE)
    group_stem = re.sub(FIELD_ID_RE, '', group_stem, flags=re.IGNORECASE)
    group_stem = re.sub(r'\b(copy)(?:\s+\d+)?\b', '', group_stem, flags=re.IGNORECASE)
    group_stem = re.sub(r'[_\-\s]+', '_', group_stem).strip('_')
    meta["group_id"] = group_stem if group_stem else clean_stem

    return meta


def _is_timepoint_text(text: str) -> bool:
    return re.search(TIMEPOINT_RE, text, flags=re.IGNORECASE) is not None


def _condition_from_parts(parts: list[str]) -> str | None:
    condition_parts = []
    for part in parts:
        if _is_timepoint_text(part):
            continue
        clean = re.sub(r'[_\-\s]+', '_', part.strip()).strip('_')
        if not clean:
            continue
        if clean.lower() in GENERIC_FOLDER_NAMES:
            continue
        condition_parts.append(clean)
    return "_".join(condition_parts) if condition_parts else None


def parse_image_metadata(image_path: Path, root_dir: Path | None = None) -> dict:
    image_path = Path(image_path)
    try:
        rel_path = image_path.relative_to(root_dir) if root_dir is not None else image_path
    except ValueError:
        rel_path = image_path

    meta = parse_filename_metadata(image_path.name)
    rel_path_str = str(rel_path)
    meta["filename"] = rel_path_str
    meta["relative_path"] = rel_path_str

    folder_parts = list(rel_path.parent.parts)
    for part in folder_parts:
        if meta["time_value"] is not None:
            break
        time_match = re.search(TIMEPOINT_RE, part, flags=re.IGNORECASE)
        if time_match:
            meta["time_raw"] = time_match.group(0)
            meta["time_value"] = int(time_match.group(1))
            meta["time_unit"] = "h"

    condition_id = _condition_from_parts(folder_parts)
    if condition_id:
        meta["condition_id"] = condition_id
        file_group = meta.get("group_id")
        if file_group and file_group != meta["stem"] and file_group.lower() not in GENERIC_FILE_GROUPS:
            meta["group_id"] = f"{condition_id}_{file_group}"
        else:
            meta["group_id"] = condition_id

    return meta


def artifact_stem(image_path: Path, root_dir: Path | None = None) -> str:
    try:
        rel = image_path.relative_to(root_dir) if root_dir is not None else image_path
    except ValueError:
        rel = image_path
    rel_no_suffix = Path(rel).with_suffix("")
    stem = re.sub(r'[^A-Za-z0-9]+', '_', str(rel_no_suffix)).strip('_')
    return stem or Path(image_path).stem


# =========================================================
# Preprocessing
# =========================================================

def preprocess(img: np.ndarray,
               blur_kernel: int = 5,
               background_kernel: int = 101,
               use_clahe: bool = True) -> np.ndarray:
    if blur_kernel % 2 == 0:
        blur_kernel += 1
    if background_kernel % 2 == 0:
        background_kernel += 1

    blur = cv2.GaussianBlur(img, (blur_kernel, blur_kernel), 0)
    bg = cv2.GaussianBlur(blur, (background_kernel, background_kernel), 0)

    corrected = blur.astype(np.float32) - bg.astype(np.float32)
    corrected = cv2.normalize(corrected, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    if use_clahe:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        corrected = clahe.apply(corrected)

    corrected = cv2.normalize(corrected, None, 0, 255, cv2.NORM_MINMAX)
    return corrected


# =========================================================
# Feature maps
# =========================================================

def local_std_map(img: np.ndarray, window: int = 21) -> np.ndarray:
    img_f = img.astype(np.float32)
    mean = cv2.boxFilter(img_f, ddepth=-1, ksize=(window, window), normalize=True)
    mean_sq = cv2.boxFilter(img_f * img_f, ddepth=-1, ksize=(window, window), normalize=True)
    var = np.maximum(mean_sq - mean * mean, 0.0)
    return np.sqrt(var)


def gradient_map(img: np.ndarray) -> np.ndarray:
    img_f = img.astype(np.float32)
    gx = cv2.Sobel(img_f, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(img_f, cv2.CV_32F, 0, 1, ksize=3)
    return np.sqrt(gx * gx + gy * gy)


def residual_texture_map(img: np.ndarray, smooth_window: int = 9) -> np.ndarray:
    img_f = img.astype(np.float32)
    mean_small = cv2.boxFilter(img_f, ddepth=-1, ksize=(smooth_window, smooth_window), normalize=True)
    return np.abs(img_f - mean_small)


def build_feature_maps(img: np.ndarray,
                       std_window: int = 21,
                       residual_window: int = 9) -> dict:
    return {
        "std_map": local_std_map(img, std_window),
        "grad_map": gradient_map(img),
        "resid_map": residual_texture_map(img, residual_window),
    }


# =========================================================
# Time-0 ROI detection
# =========================================================

def compute_column_profiles_from_maps(feature_maps: dict) -> dict:
    return {
        "std_profile": feature_maps["std_map"].mean(axis=0),
        "grad_profile": feature_maps["grad_map"].mean(axis=0),
        "resid_profile": feature_maps["resid_map"].mean(axis=0),
    }


def build_corridor_score(column_profiles: dict, smooth_window: int = 31) -> dict:
    std_p = moving_average_1d(column_profiles["std_profile"], smooth_window)
    grad_p = moving_average_1d(column_profiles["grad_profile"], smooth_window)
    resid_p = moving_average_1d(column_profiles["resid_profile"], smooth_window)

    std_n = normalize_0_1(std_p)
    grad_n = normalize_0_1(grad_p)
    resid_n = normalize_0_1(resid_p)

    corridor_score = (
        0.45 * (1.0 - std_n) +
        0.35 * (1.0 - grad_n) +
        0.20 * (1.0 - resid_n)
    )

    return {
        "std_profile_smooth": std_p,
        "grad_profile_smooth": grad_p,
        "resid_profile_smooth": resid_p,
        "corridor_score": corridor_score,
    }


def choose_vertical_corridor(corridor_score: np.ndarray,
                             min_width: int,
                             max_width_fraction: float = 0.8) -> tuple[int, int, float]:
    n = len(corridor_score)
    max_width = max(min_width, int(n * max_width_fraction))
    center = n / 2.0

    thr = np.percentile(corridor_score, 75)
    candidate = corridor_score >= thr
    runs = contiguous_true_runs(candidate)

    valid = []
    for left, right in runs:
        width = right - left + 1
        if width < min_width or width > max_width:
            continue
        mean_score = float(corridor_score[left:right + 1].mean())
        band_center = (left + right) / 2.0
        centrality = 1.0 / (1.0 + abs(band_center - center))
        final_score = mean_score + 0.15 * centrality
        valid.append((left, right, final_score))

    if valid:
        valid.sort(key=lambda x: x[2], reverse=True)
        return valid[0]

    best_left, best_right, best_score = 0, min_width - 1, -np.inf
    csum = np.cumsum(np.r_[0.0, corridor_score])

    for width in range(min_width, min(max_width, n) + 1):
        means = (csum[width:] - csum[:-width]) / width
        for left, mean_score in enumerate(means):
            right = left + width - 1
            band_center = (left + right) / 2.0
            centrality = 1.0 / (1.0 + abs(band_center - center))
            final_score = float(mean_score + 0.15 * centrality)
            if final_score > best_score:
                best_score = final_score
                best_left = left
                best_right = right

    return best_left, best_right, float(best_score)


def detect_t0_corridor(processed_img: np.ndarray,
                       feature_maps: dict,
                       smooth_window: int = 31,
                       min_corridor_width: int = 20) -> dict:
    col_profiles = compute_column_profiles_from_maps(feature_maps)
    score_data = build_corridor_score(col_profiles, smooth_window=smooth_window)

    left, right, score = choose_vertical_corridor(
        score_data["corridor_score"],
        min_width=min_corridor_width,
        max_width_fraction=0.8
    )

    center = int(round((left + right) / 2.0))
    h, w = processed_img.shape
    mask = np.zeros((h, w), dtype=bool)
    mask[:, left:right + 1] = True

    return {
        "roi_left": int(left),
        "roi_right": int(right),
        "roi_center": int(center),
        "roi_width_px": int(right - left + 1),
        "roi_mask": mask,
        "t0_corridor_score": float(score),
    }


# =========================================================
# Build time-0 references
# =========================================================

def build_t0_reference_table(image_paths,
                             root_dir,
                             blur_kernel,
                             background_kernel,
                             std_window,
                             residual_window,
                             corridor_smooth_window,
                             min_corridor_width,
                             threshold_mode="hybrid",
                             percentile_value=60.0,
                             min_open_object_size=100,
                             morph_close=5,
                             morph_open=3) -> pd.DataFrame:
    rows = []

    for image_path in image_paths:
        meta = parse_image_metadata(image_path, root_dir=root_dir)
        if meta["time_value"] != 0:
            continue

        img = load_gray(image_path)
        proc = preprocess(img, blur_kernel=blur_kernel, background_kernel=background_kernel, use_clahe=True)
        fmap = build_feature_maps(proc, std_window=std_window, residual_window=residual_window)
        t0 = detect_t0_corridor(proc, fmap, smooth_window=corridor_smooth_window, min_corridor_width=min_corridor_width)
        freehand_roi = build_full_image_roi(proc.shape)
        freehand_masks = build_masks(
            img=proc,
            feature_maps=fmap,
            roi_data=freehand_roi,
            threshold_mode=threshold_mode,
            percentile_value=percentile_value,
            min_open_object_size=min_open_object_size,
            morph_close=morph_close,
            morph_open=morph_open,
        )
        geometry = classify_wound_geometry(freehand_masks["open_mask"], proc.shape)

        rows.append({
            "filename": image_path.name,
            "well_id": meta["well_id"],
            "field_id": meta["field_id"],
            "condition_id": meta["condition_id"],
            "group_id": meta["group_id"],
            "t0_left_px": t0["roi_left"],
            "t0_right_px": t0["roi_right"],
            "t0_center_px": t0["roi_center"],
            "t0_width_px": t0["roi_width_px"],
            "t0_wound_geometry": geometry["wound_geometry"],
            "t0_geometry_score": geometry["geometry_score"],
            "t0_width_cv": geometry["width_cv"],
            "t0_center_cv": geometry["center_cv"],
            "t0_orientation_deg": geometry["orientation_deg"],
        })

    return pd.DataFrame(rows)


def get_t0_reference(meta: dict, t0_ref_df: pd.DataFrame) -> tuple[dict, str]:
    well_id = meta.get("well_id")
    field_id = meta.get("field_id")
    condition_id = meta.get("condition_id")
    group_id = meta.get("group_id")

    if field_id is not None and not t0_ref_df.empty:
        g = t0_ref_df[t0_ref_df["field_id"] == field_id]
        if condition_id is not None and "condition_id" in g.columns:
            scoped = g[g["condition_id"] == condition_id]
            if not scoped.empty:
                g = scoped
        if not g.empty:
            row = g.iloc[0]
            return {
                "t0_left": int(row["t0_left_px"]),
                "t0_right": int(row["t0_right_px"]),
                "t0_center": int(row["t0_center_px"]),
                "t0_width": int(row["t0_width_px"]),
                "t0_wound_geometry": row.get("t0_wound_geometry", "insert"),
                "t0_geometry_score": float(row.get("t0_geometry_score", np.nan)),
            }, "field_t0"

    if well_id is not None and "well_id" in t0_ref_df.columns and not t0_ref_df.empty:
        g = t0_ref_df[t0_ref_df["well_id"] == well_id]
        if condition_id is not None and "condition_id" in g.columns:
            scoped = g[g["condition_id"] == condition_id]
            if not scoped.empty:
                g = scoped
        if not g.empty:
            return {
                "t0_left": int(round(g["t0_left_px"].median())),
                "t0_right": int(round(g["t0_right_px"].median())),
                "t0_center": int(round(g["t0_center_px"].median())),
                "t0_width": int(round(g["t0_width_px"].median())),
                "t0_wound_geometry": most_common_nonnull(g, "t0_wound_geometry", "insert"),
                "t0_geometry_score": float(pd.to_numeric(g.get("t0_geometry_score"), errors="coerce").median()) if "t0_geometry_score" in g else np.nan,
            }, "well_t0_median"

    if group_id is not None and not t0_ref_df.empty:
        g = t0_ref_df[t0_ref_df["group_id"] == group_id]
        if not g.empty:
            return {
                "t0_left": int(round(g["t0_left_px"].median())),
                "t0_right": int(round(g["t0_right_px"].median())),
                "t0_center": int(round(g["t0_center_px"].median())),
                "t0_width": int(round(g["t0_width_px"].median())),
                "t0_wound_geometry": most_common_nonnull(g, "t0_wound_geometry", "insert"),
                "t0_geometry_score": float(pd.to_numeric(g.get("t0_geometry_score"), errors="coerce").median()) if "t0_geometry_score" in g else np.nan,
            }, "group_t0_median"

    raise ValueError("No usable time-0 ROI reference found for this image.")


# =========================================================
# Leading-edge detection
# =========================================================

def build_column_cellness(feature_maps: dict, smooth_window: int = 21) -> dict:
    std_p = moving_average_1d(feature_maps["std_map"].mean(axis=0), smooth_window)
    grad_p = moving_average_1d(feature_maps["grad_map"].mean(axis=0), smooth_window)
    resid_p = moving_average_1d(feature_maps["resid_map"].mean(axis=0), smooth_window)

    std_n = normalize_0_1(std_p)
    grad_n = normalize_0_1(grad_p)
    resid_n = normalize_0_1(resid_p)

    cellness = 0.45 * std_n + 0.35 * grad_n + 0.20 * resid_n
    return {
        "std_profile": std_p,
        "grad_profile": grad_p,
        "resid_profile": resid_p,
        "cellness_profile": cellness,
    }


def detect_left_leading_edge(processed_img: np.ndarray,
                             feature_maps: dict,
                             expected_left_x: int,
                             search_radius: int = 120,
                             edge_smooth_window: int = 21,
                             min_run_width: int = 12) -> dict:
    """
    Detect the leftmost wound edge by searching near the expected left edge.
    We assume:
    - left of the wound = cell-rich region
    - wound corridor = lower-texture region
    """
    h, w = processed_img.shape
    profiles = build_column_cellness(feature_maps, smooth_window=edge_smooth_window)
    cellness = profiles["cellness_profile"]

    x0 = max(0, expected_left_x - search_radius)
    x1 = min(w - 1, expected_left_x + search_radius)
    local = cellness[x0:x1 + 1]

    # Adaptive threshold for "cell-rich"
    thr = np.percentile(local, 60)
    cell_mask = local >= thr

    # Smooth 1D mask
    cell_mask_u8 = (cell_mask.astype(np.uint8) * 255)
    cell_mask_u8 = cv2.medianBlur(cell_mask_u8.reshape(1, -1), 5).ravel()
    cell_mask = cell_mask_u8 > 0

    runs = contiguous_true_runs(cell_mask)

    candidates = []
    for s, e in runs:
        width = e - s + 1
        if width >= min_run_width:
            abs_s = x0 + s
            abs_e = x0 + e
            # left leading edge is the rightmost point of a cell run on the left side
            edge_x = abs_e
            dist_penalty = abs(edge_x - expected_left_x)
            score = float(local[s:e + 1].mean()) - 0.002 * dist_penalty
            candidates.append((edge_x, score))

    if candidates:
        candidates.sort(key=lambda t: t[1], reverse=True)
        edge_x = int(candidates[0][0])
    else:
        # fallback: use strongest gradient in search window
        grad_local = np.abs(np.gradient(local))
        edge_x = int(x0 + np.argmax(grad_local))

    return {
        "left_edge_x": int(edge_x),
        "search_x0": int(x0),
        "search_x1": int(x1),
        "cellness_profile": profiles["cellness_profile"],
        "std_profile": profiles["std_profile"],
        "grad_profile": profiles["grad_profile"],
        "resid_profile": profiles["resid_profile"],
        "cell_threshold": float(thr) if len(local) else np.nan,
    }


def build_left_anchored_roi(img_shape: tuple[int, int],
                            left_edge_x: int,
                            t0_width: int) -> dict:
    h, w = img_shape
    left = int(left_edge_x)
    right = left + int(t0_width) - 1

    if left < 0:
        left = 0
        right = min(w - 1, t0_width - 1)

    if right >= w:
        right = w - 1
        left = max(0, w - t0_width)

    mask = np.zeros((h, w), dtype=bool)
    mask[:, left:right + 1] = True

    return {
        "roi_left": int(left),
        "roi_right": int(right),
        "roi_center": int(round((left + right) / 2.0)),
        "roi_width_px": int(right - left + 1),
        "roi_mask": mask,
    }


def build_full_image_roi(img_shape: tuple[int, int]) -> dict:
    h, w = img_shape
    mask = np.ones((h, w), dtype=bool)
    return {
        "roi_left": 0,
        "roi_right": int(w - 1),
        "roi_center": int(round((w - 1) / 2.0)),
        "roi_width_px": int(w),
        "roi_mask": mask,
    }


def largest_component_mask(mask: np.ndarray, min_area: int = 1) -> np.ndarray:
    mask_u8 = (mask.astype(np.uint8) * 255)
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask_u8, connectivity=8)
    if num_labels <= 1:
        return np.zeros_like(mask, dtype=bool)

    best_label = None
    best_area = 0
    for lab in range(1, num_labels):
        area = int(stats[lab, cv2.CC_STAT_AREA])
        if area >= min_area and area > best_area:
            best_label = lab
            best_area = area

    if best_label is None:
        return np.zeros_like(mask, dtype=bool)
    return labels == best_label


def classify_wound_geometry(open_mask: np.ndarray,
                            image_shape: tuple[int, int],
                            min_rows_fraction: float = 0.35) -> dict:
    h, w = image_shape
    main_mask = largest_component_mask(open_mask, min_area=max(50, int(h * w * 0.002)))
    row_widths = row_open_widths(main_mask)
    active_rows = row_widths > 0
    active_fraction = float(np.mean(active_rows)) if len(active_rows) else 0.0

    if not np.any(active_rows) or active_fraction < min_rows_fraction:
        return {
            "wound_geometry": "freehand",
            "geometry_score": 0.0,
            "width_cv": np.nan,
            "center_cv": np.nan,
            "orientation_deg": np.nan,
            "active_row_fraction": active_fraction,
        }

    widths = row_widths[active_rows].astype(float)
    centers = []
    for y in np.where(active_rows)[0]:
        xs = np.where(main_mask[y])[0]
        centers.append(float((xs.min() + xs.max()) / 2.0))
    centers = np.asarray(centers, dtype=float)

    width_cv = float(np.std(widths) / max(np.mean(widths), 1.0))
    center_cv = float(np.std(centers) / max(w, 1))

    ys, xs = np.where(main_mask)
    if len(xs) > 2:
        coords = np.column_stack([xs.astype(float), ys.astype(float)])
        coords -= coords.mean(axis=0)
        _, _, vh = np.linalg.svd(coords, full_matrices=False)
        vx, vy = vh[0]
        orientation_deg = float(abs(np.degrees(np.arctan2(vy, vx))))
        orientation_from_vertical = abs(90.0 - orientation_deg)
    else:
        orientation_deg = np.nan
        orientation_from_vertical = 90.0

    regular_width_score = max(0.0, 1.0 - width_cv / 0.65)
    straight_center_score = max(0.0, 1.0 - center_cv / 0.12)
    vertical_score = max(0.0, 1.0 - orientation_from_vertical / 35.0)
    coverage_score = min(1.0, active_fraction / 0.85)
    geometry_score = float(
        0.35 * regular_width_score +
        0.35 * straight_center_score +
        0.20 * vertical_score +
        0.10 * coverage_score
    )
    wound_geometry = "insert" if geometry_score >= 0.58 else "freehand"

    return {
        "wound_geometry": wound_geometry,
        "geometry_score": geometry_score,
        "width_cv": width_cv,
        "center_cv": center_cv,
        "orientation_deg": orientation_deg,
        "active_row_fraction": active_fraction,
    }


def build_freehand_roi_from_mask(open_mask: np.ndarray,
                                 img_shape: tuple[int, int],
                                 padding_px: int = 24,
                                 min_area: int = 100) -> dict:
    h, w = img_shape
    main_mask = largest_component_mask(open_mask, min_area=min_area)
    if not np.any(main_mask):
        return build_full_image_roi(img_shape)

    k = max(3, int(padding_px) * 2 + 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    roi_u8 = cv2.dilate((main_mask.astype(np.uint8) * 255), kernel, iterations=1)
    roi_mask = roi_u8 > 0
    ys, xs = np.where(roi_mask)

    return {
        "roi_left": int(xs.min()),
        "roi_right": int(xs.max()),
        "roi_center": int(round((xs.min() + xs.max()) / 2.0)),
        "roi_width_px": int(xs.max() - xs.min() + 1),
        "roi_mask": roi_mask,
    }


# =========================================================
# Open-area segmentation inside ROI
# =========================================================

def otsu_threshold_from_values(vals_0_1: np.ndarray) -> float:
    vals_u8 = np.clip(vals_0_1 * 255.0, 0, 255).astype(np.uint8)
    thr_u8, _ = cv2.threshold(vals_u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return float(thr_u8) / 255.0


def threshold_open_within_roi(img: np.ndarray,
                              feature_maps: dict,
                              roi_mask: np.ndarray,
                              threshold_mode: str = "hybrid",
                              percentile_value: float = 60.0,
                              bright_open: bool = None) -> dict:
    roi_idx = roi_mask.astype(bool)
    if roi_idx.sum() == 0:
        raise ValueError("ROI mask is empty.")

    std_vals = feature_maps["std_map"][roi_idx]
    grad_vals = feature_maps["grad_map"][roi_idx]
    resid_vals = feature_maps["resid_map"][roi_idx]
    inten_vals = img[roi_idx].astype(np.float32)

    std_n = normalize_0_1(std_vals)
    grad_n = normalize_0_1(grad_vals)
    resid_n = normalize_0_1(resid_vals)
    inten_n = normalize_0_1(inten_vals)

    if bright_open is None:
        low_texture = std_n < np.percentile(std_n, 30)
        high_texture = std_n > np.percentile(std_n, 70)
        if low_texture.sum() > 10 and high_texture.sum() > 10:
            bright_open = float(np.median(inten_n[low_texture])) >= float(np.median(inten_n[high_texture]))
        else:
            bright_open = True

    intensity_term = inten_n if bright_open else (1.0 - inten_n)

    open_score_vals = (
        0.40 * (1.0 - std_n) +
        0.30 * (1.0 - grad_n) +
        0.20 * (1.0 - resid_n) +
        0.10 * intensity_term
    )

    if threshold_mode == "percentile":
        thr = float(np.percentile(open_score_vals, percentile_value))
        thr_source = f"percentile_{percentile_value:g}"
    elif threshold_mode == "otsu":
        thr = otsu_threshold_from_values(open_score_vals)
        thr_source = "otsu"
    elif threshold_mode == "hybrid":
        thr_p = float(np.percentile(open_score_vals, percentile_value))
        thr_o = otsu_threshold_from_values(open_score_vals)
        thr = 0.5 * (thr_p + thr_o)
        thr_source = f"hybrid_p{percentile_value:g}_otsu"
    else:
        raise ValueError(f"Unknown threshold_mode: {threshold_mode}")

    open_binary_vals = open_score_vals >= thr

    open_score_map = np.zeros_like(img, dtype=np.float32)
    open_mask_raw = np.zeros_like(img, dtype=bool)
    open_score_map[roi_idx] = open_score_vals
    open_mask_raw[roi_idx] = open_binary_vals

    return {
        "open_score_map": open_score_map,
        "open_mask_raw": open_mask_raw,
        "bright_open": bool(bright_open),
        "open_threshold_value": float(thr),
        "open_threshold_source": thr_source,
    }


def clean_open_mask(open_mask: np.ndarray,
                    roi_mask: np.ndarray,
                    min_object_size: int = 100,
                    close_kernel: int = 5,
                    open_kernel: int = 3) -> np.ndarray:
    mask_u8 = (open_mask.astype(np.uint8) * 255)

    if open_kernel > 1:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_kernel, open_kernel))
        mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_OPEN, k)

    if close_kernel > 1:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_kernel, close_kernel))
        mask_u8 = cv2.morphologyEx(mask_u8, cv2.MORPH_CLOSE, k)

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask_u8, connectivity=8)
    cleaned = np.zeros_like(mask_u8)

    for lab in range(1, num_labels):
        area = stats[lab, cv2.CC_STAT_AREA]
        if area >= min_object_size:
            cleaned[labels == lab] = 255

    return (cleaned > 0) & roi_mask


def build_masks(img: np.ndarray,
                feature_maps: dict,
                roi_data: dict,
                threshold_mode: str,
                percentile_value: float,
                min_open_object_size: int,
                morph_close: int,
                morph_open: int) -> dict:
    thresh_data = threshold_open_within_roi(
        img=img,
        feature_maps=feature_maps,
        roi_mask=roi_data["roi_mask"],
        threshold_mode=threshold_mode,
        percentile_value=percentile_value,
        bright_open=None
    )

    open_mask = clean_open_mask(
        open_mask=thresh_data["open_mask_raw"],
        roi_mask=roi_data["roi_mask"],
        min_object_size=min_open_object_size,
        close_kernel=morph_close,
        open_kernel=morph_open
    )

    occupied_mask = roi_data["roi_mask"] & (~open_mask)

    return {
        "open_mask": open_mask,
        "occupied_mask": occupied_mask,
        "open_score_map": thresh_data["open_score_map"],
        "bright_open": thresh_data["bright_open"],
        "open_threshold_value": thresh_data["open_threshold_value"],
        "open_threshold_source": thresh_data["open_threshold_source"],
    }


# =========================================================
# Measurements
# =========================================================

def row_open_widths(open_mask: np.ndarray) -> np.ndarray:
    h, _ = open_mask.shape
    widths = np.zeros(h, dtype=int)
    for y in range(h):
        xs = np.where(open_mask[y])[0]
        if len(xs) > 1:
            widths[y] = int(xs[-1] - xs[0] + 1)
    return widths


def measure_masks(open_mask: np.ndarray,
                  occupied_mask: np.ndarray,
                  roi_mask: np.ndarray) -> dict:
    open_area = int(open_mask.sum())
    occupied_area = int(occupied_mask.sum())
    roi_area = int(roi_mask.sum())

    row_widths = row_open_widths(open_mask)
    open_rows = row_widths > 0

    if open_area > 0:
        ys, xs = np.where(open_mask)
        xmin, xmax = int(xs.min()), int(xs.max())
        ymin, ymax = int(ys.min()), int(ys.max())
    else:
        xmin = xmax = ymin = ymax = np.nan

    return {
        "residual_open_area_px": open_area,
        "occupied_area_in_roi_px": occupied_area,
        "analysis_roi_area_px": roi_area,
        "open_fraction_of_roi": (open_area / roi_area) if roi_area > 0 else np.nan,
        "occupied_fraction_of_roi": (occupied_area / roi_area) if roi_area > 0 else np.nan,
        "mean_open_width_px": float(np.mean(row_widths[row_widths > 0])) if np.any(row_widths > 0) else 0.0,
        "median_open_width_px": float(np.median(row_widths[row_widths > 0])) if np.any(row_widths > 0) else 0.0,
        "max_open_width_px": float(np.max(row_widths)) if len(row_widths) else 0.0,
        "fraction_open_rows": float(np.mean(open_rows)) if len(open_rows) else 0.0,
        "percent_rows_closed": 100.0 * (1.0 - float(np.mean(open_rows))) if len(open_rows) else 100.0,
        "bbox_xmin": xmin,
        "bbox_xmax": xmax,
        "bbox_ymin": ymin,
        "bbox_ymax": ymax,
    }


def qc_flags(open_mask: np.ndarray,
             roi_mask: np.ndarray,
             image_shape: tuple[int, int]) -> dict:
    _, w = image_shape
    open_area = int(open_mask.sum())
    roi_area = int(roi_mask.sum())

    if roi_area == 0:
        return {
            "flag_empty_roi": True,
            "flag_empty_open_mask": True,
            "flag_open_touches_left_border": False,
            "flag_open_touches_right_border": False,
            "flag_nearly_closed": False,
        }

    if open_area == 0:
        return {
            "flag_empty_roi": False,
            "flag_empty_open_mask": True,
            "flag_open_touches_left_border": False,
            "flag_open_touches_right_border": False,
            "flag_nearly_closed": True,
        }

    ys, xs = np.where(open_mask)
    touches_left = xs.min() == 0
    touches_right = xs.max() == w - 1
    nearly_closed = (open_area / roi_area) < 0.05

    return {
        "flag_empty_roi": False,
        "flag_empty_open_mask": False,
        "flag_open_touches_left_border": bool(touches_left),
        "flag_open_touches_right_border": bool(touches_right),
        "flag_nearly_closed": bool(nearly_closed),
    }


# =========================================================
# Closure metrics
# =========================================================

def add_closure_metrics(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["reference_open_area_px"] = np.nan
    df["reference_type"] = None
    df["percent_closure"] = np.nan

    if "time_value" not in df.columns or "residual_open_area_px" not in df.columns:
        return df

    if "field_id" in df.columns:
        group_cols = ["field_id"]
        if "condition_id" in df.columns:
            group_cols = ["condition_id", "field_id"]
        for _, g in df.groupby(group_cols, dropna=True):
            g0 = g[g["time_value"] == 0]
            if not g0.empty:
                ref = float(g0["residual_open_area_px"].median())
                if ref > 0:
                    idx = g.index
                    df.loc[idx, "reference_open_area_px"] = ref
                    df.loc[idx, "reference_type"] = "field_t0_open_area"
                    df.loc[idx, "percent_closure"] = 100.0 * (
                        1.0 - df.loc[idx, "residual_open_area_px"] / ref
                    )

    if "well_id" in df.columns:
        group_cols = ["well_id"]
        if "condition_id" in df.columns:
            group_cols = ["condition_id", "well_id"]
        for _, g in df.groupby(group_cols, dropna=True):
            missing_idx = g[g["reference_open_area_px"].isna()].index
            if len(missing_idx) == 0:
                continue
            g0 = g[g["time_value"] == 0]
            if not g0.empty:
                ref = float(g0["residual_open_area_px"].median())
                if ref > 0:
                    df.loc[missing_idx, "reference_open_area_px"] = ref
                    df.loc[missing_idx, "reference_type"] = "well_t0_open_area"
                    df.loc[missing_idx, "percent_closure"] = 100.0 * (
                        1.0 - df.loc[missing_idx, "residual_open_area_px"] / ref
                    )

    if "group_id" in df.columns:
        for group_id, g in df.groupby("group_id", dropna=True):
            missing_idx = g[g["reference_open_area_px"].isna()].index
            if len(missing_idx) == 0:
                continue
            g0 = g[g["time_value"] == 0]
            if not g0.empty:
                ref = float(g0["residual_open_area_px"].median())
                if ref > 0:
                    df.loc[missing_idx, "reference_open_area_px"] = ref
                    df.loc[missing_idx, "reference_type"] = "group_t0_open_area_median"
                    df.loc[missing_idx, "percent_closure"] = 100.0 * (
                        1.0 - df.loc[missing_idx, "residual_open_area_px"] / ref
                    )

    return df


# =========================================================
# Output
# =========================================================

def save_mask(mask: np.ndarray, out_path: Path) -> None:
    cv2.imwrite(str(out_path), (mask.astype(np.uint8) * 255))


def save_overlay(original: np.ndarray,
                 roi_mask: np.ndarray,
                 open_mask: np.ndarray,
                 left_edge_x: int,
                 out_path: Path) -> None:
    overlay = cv2.cvtColor(original, cv2.COLOR_GRAY2BGR)

    roi_u8 = roi_mask.astype(np.uint8)
    contours, _ = cv2.findContours(roi_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(overlay, contours, -1, (255, 0, 0), 1)

    open_u8 = open_mask.astype(np.uint8)
    contours, _ = cv2.findContours(open_u8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(overlay, contours, -1, (0, 0, 255), 1)

    overlay[open_mask] = (0.4 * overlay[open_mask] + 0.6 * np.array([0, 0, 255])).astype(np.uint8)

    if left_edge_x is not None and not pd.isna(left_edge_x):
        h = original.shape[0]
        cv2.line(overlay, (int(left_edge_x), 0), (int(left_edge_x), h - 1), (0, 255, 0), 1)

    cv2.imwrite(str(out_path), overlay)


def save_debug_panel(original: np.ndarray,
                     processed: np.ndarray,
                     edge_data: dict,
                     roi_data: dict,
                     mask_data: dict,
                     out_path: Path,
                     title: str = "") -> None:
    fig, axes = plt.subplots(2, 3, figsize=(17, 10))

    axes[0, 0].imshow(original, cmap="gray")
    axes[0, 0].set_title("Original")
    axes[0, 0].axis("off")

    axes[0, 1].imshow(processed, cmap="gray")
    axes[0, 1].set_title("Processed")
    axes[0, 1].axis("off")

    overlay = cv2.cvtColor(original, cv2.COLOR_GRAY2RGB)
    overlay[mask_data["open_mask"]] = [255, 0, 0]
    axes[0, 2].imshow(overlay)
    if edge_data.get("left_edge_x") is not None and not pd.isna(edge_data.get("left_edge_x")):
        axes[0, 2].axvline(edge_data["left_edge_x"], color="lime", linewidth=1)
    axes[0, 2].axvline(roi_data["roi_right"], color="cyan", linewidth=1)
    axes[0, 2].set_title("Detected Open Area + ROI")
    axes[0, 2].axis("off")

    if "cellness_profile" in edge_data:
        axes[1, 0].plot(edge_data["cellness_profile"])
        if edge_data.get("left_edge_x") is not None and not pd.isna(edge_data.get("left_edge_x")):
            axes[1, 0].axvline(edge_data["left_edge_x"], color="lime", linewidth=1)
        axes[1, 0].axvline(edge_data["search_x0"], color="gray", linestyle="--", linewidth=1)
        axes[1, 0].axvline(edge_data["search_x1"], color="gray", linestyle="--", linewidth=1)
        axes[1, 0].set_title("Column Cellness Profile")
    else:
        axes[1, 0].imshow(mask_data["open_mask"], cmap="gray")
        axes[1, 0].set_title("Freehand Open Mask")
        axes[1, 0].axis("off")

    axes[1, 1].imshow(mask_data["open_score_map"], cmap="viridis")
    axes[1, 1].set_title(f"Open Score Map ({mask_data['open_threshold_source']})")
    axes[1, 1].axis("off")

    roi_vis = np.zeros_like(processed, dtype=np.uint8)
    roi_vis[roi_data["roi_mask"]] = 255
    axes[1, 2].imshow(roi_vis, cmap="gray")
    if edge_data.get("left_edge_x") is not None and not pd.isna(edge_data.get("left_edge_x")):
        axes[1, 2].axvline(edge_data["left_edge_x"], color="lime", linewidth=1)
    axes[1, 2].set_title("Analysis ROI")
    axes[1, 2].axis("off")

    fig.suptitle(title)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)


# =========================================================
# Analyze one image
# =========================================================

def analyze_image(image_path: Path,
                  root_dir: Path,
                  t0_ref_df: pd.DataFrame,
                  mask_dir: Path,
                  overlay_dir: Path,
                  debug_dir: Path,
                  wound_geometry_mode: str,
                  blur_kernel: int,
                  background_kernel: int,
                  std_window: int,
                  residual_window: int,
                  threshold_mode: str,
                  percentile_value: float,
                  min_open_object_size: int,
                  morph_close: int,
                  morph_open: int,
                  leading_edge_search_radius: int,
                  edge_smooth_window: int,
                  min_cell_run_width: int) -> dict:
    original = load_gray(image_path)
    processed = preprocess(
        original,
        blur_kernel=blur_kernel,
        background_kernel=background_kernel,
        use_clahe=True
    )

    feature_maps = build_feature_maps(
        processed,
        std_window=std_window,
        residual_window=residual_window
    )

    meta = parse_image_metadata(image_path, root_dir=root_dir)
    out_stem = artifact_stem(image_path, root_dir=root_dir)
    t0_ref, t0_ref_source = get_t0_reference(meta, t0_ref_df)
    if wound_geometry_mode == "auto":
        selected_wound_geometry = t0_ref.get("t0_wound_geometry") or "insert"
    else:
        selected_wound_geometry = wound_geometry_mode

    if selected_wound_geometry not in {"insert", "freehand"}:
        raise ValueError(f"Unknown wound geometry mode: {wound_geometry_mode}")

    if selected_wound_geometry == "insert":
        edge_data = detect_left_leading_edge(
            processed_img=processed,
            feature_maps=feature_maps,
            expected_left_x=t0_ref["t0_left"],
            search_radius=leading_edge_search_radius,
            edge_smooth_window=edge_smooth_window,
            min_run_width=min_cell_run_width
        )

        roi_data = build_left_anchored_roi(
            img_shape=processed.shape,
            left_edge_x=edge_data["left_edge_x"],
            t0_width=t0_ref["t0_width"]
        )
    else:
        full_roi = build_full_image_roi(processed.shape)
        first_pass_masks = build_masks(
            img=processed,
            feature_maps=feature_maps,
            roi_data=full_roi,
            threshold_mode=threshold_mode,
            percentile_value=percentile_value,
            min_open_object_size=min_open_object_size,
            morph_close=morph_close,
            morph_open=morph_open
        )
        roi_data = build_freehand_roi_from_mask(
            open_mask=first_pass_masks["open_mask"],
            img_shape=processed.shape,
            padding_px=max(12, int(round(t0_ref["t0_width"] * 0.08))),
            min_area=min_open_object_size,
        )
        edge_data = {
            "left_edge_x": np.nan,
            "search_x0": int(roi_data["roi_left"]),
            "search_x1": int(roi_data["roi_right"]),
        }

    mask_data = build_masks(
        img=processed,
        feature_maps=feature_maps,
        roi_data=roi_data,
        threshold_mode=threshold_mode,
        percentile_value=percentile_value,
        min_open_object_size=min_open_object_size,
        morph_close=morph_close,
        morph_open=morph_open
    )

    if selected_wound_geometry == "freehand":
        dominant_open_mask = largest_component_mask(mask_data["open_mask"], min_area=min_open_object_size)
        if np.any(dominant_open_mask):
            mask_data["open_mask"] = dominant_open_mask & roi_data["roi_mask"]
            mask_data["occupied_mask"] = roi_data["roi_mask"] & (~mask_data["open_mask"])

    open_mask = mask_data["open_mask"]
    occupied_mask = roi_data["roi_mask"] & (~open_mask)

    save_mask(open_mask, mask_dir / f"{out_stem}_open_mask.png")
    save_overlay(
        original=original,
        roi_mask=roi_data["roi_mask"],
        open_mask=open_mask,
        left_edge_x=edge_data.get("left_edge_x"),
        out_path=overlay_dir / f"{out_stem}_overlay.png"
    )
    save_debug_panel(
        original=original,
        processed=processed,
        edge_data=edge_data,
        roi_data=roi_data,
        mask_data=mask_data,
        out_path=debug_dir / f"{out_stem}_debug.png",
        title=meta["relative_path"]
    )

    metrics = measure_masks(open_mask, occupied_mask, roi_data["roi_mask"])
    flags = qc_flags(open_mask, roi_data["roi_mask"], original.shape)

    return {
        **meta,
        **metrics,
        **flags,
        "image_height_px": int(original.shape[0]),
        "image_width_px": int(original.shape[1]),
        "t0_reference_source": t0_ref_source,
        "wound_geometry_mode": wound_geometry_mode,
        "selected_wound_geometry": selected_wound_geometry,
        "t0_wound_geometry": t0_ref.get("t0_wound_geometry"),
        "t0_geometry_score": t0_ref.get("t0_geometry_score"),
        "detected_left_edge_px": int(edge_data["left_edge_x"]) if not pd.isna(edge_data.get("left_edge_x")) else np.nan,
        "analysis_roi_left_px": int(roi_data["roi_left"]),
        "analysis_roi_right_px": int(roi_data["roi_right"]),
        "analysis_roi_center_px": int(roi_data["roi_center"]),
        "analysis_roi_width_px": int(roi_data["roi_width_px"]),
        "bright_open_assumption": bool(mask_data["bright_open"]),
        "open_threshold_value": float(mask_data["open_threshold_value"]),
        "open_threshold_source": mask_data["open_threshold_source"],
    }


# =========================================================
# Folder analysis
# =========================================================

def analyze_folder(input_dir: Path,
                   output_dir: Path,
                   wound_geometry_mode: str,
                   blur_kernel: int,
                   background_kernel: int,
                   std_window: int,
                   residual_window: int,
                   corridor_smooth_window: int,
                   min_corridor_width: int,
                   threshold_mode: str,
                   percentile_value: float,
                   min_open_object_size: int,
                   morph_close: int,
                   morph_open: int,
                   leading_edge_search_radius: int,
                   edge_smooth_window: int,
                   min_cell_run_width: int) -> pd.DataFrame:
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)

    mask_dir = output_dir / "masks"
    overlay_dir = output_dir / "overlays"
    debug_dir = output_dir / "debug"

    ensure_dir(output_dir)
    ensure_dir(mask_dir)
    ensure_dir(overlay_dir)
    ensure_dir(debug_dir)

    image_paths = []
    for ext in ["*.tif", "*.TIF", "*.tiff", "*.TIFF", "*.png", "*.jpg", "*.jpeg", "*.JPG", "*.JPEG"]:
        image_paths.extend(sorted(input_dir.rglob(ext)))

    if not image_paths:
        raise ValueError(f"No images found in {input_dir}")

    t0_ref_df = build_t0_reference_table(
        image_paths=image_paths,
        root_dir=input_dir,
        blur_kernel=blur_kernel,
        background_kernel=background_kernel,
        std_window=std_window,
        residual_window=residual_window,
        corridor_smooth_window=corridor_smooth_window,
        min_corridor_width=min_corridor_width,
        threshold_mode=threshold_mode,
        percentile_value=percentile_value,
        min_open_object_size=min_open_object_size,
        morph_close=morph_close,
        morph_open=morph_open
    )

    if t0_ref_df.empty:
        raise ValueError("No time-0 images found.")

    results = []

    for image_path in image_paths:
        print(f"Analyzing: {image_path.name}")
        try:
            row = analyze_image(
                image_path=image_path,
                root_dir=input_dir,
                t0_ref_df=t0_ref_df,
                mask_dir=mask_dir,
                overlay_dir=overlay_dir,
                debug_dir=debug_dir,
                wound_geometry_mode=wound_geometry_mode,
                blur_kernel=blur_kernel,
                background_kernel=background_kernel,
                std_window=std_window,
                residual_window=residual_window,
                threshold_mode=threshold_mode,
                percentile_value=percentile_value,
                min_open_object_size=min_open_object_size,
                morph_close=morph_close,
                morph_open=morph_open,
                leading_edge_search_radius=leading_edge_search_radius,
                edge_smooth_window=edge_smooth_window,
                min_cell_run_width=min_cell_run_width
            )
            print(
                f"  -> geometry={row.get('selected_wound_geometry', '')} | "
                f"left_edge={row['detected_left_edge_px']} | "
                f"open_area={row['residual_open_area_px']} | "
                f"roi_width={row['analysis_roi_width_px']}"
            )
            results.append(row)
        except Exception as e:
            print(f"  !! Failed on {image_path.name}: {e}")
            meta = parse_image_metadata(image_path, root_dir=input_dir)
            results.append({
                **meta,
                "error": str(e)
            })

    df = pd.DataFrame(results)
    df = add_closure_metrics(df)

    out_csv = output_dir / "scratch_results.csv"
    df.to_csv(out_csv, index=False)
    print(f"\nSaved results to: {out_csv}")

    return df


# =========================================================
# CLI
# =========================================================

def build_parser():
    parser = argparse.ArgumentParser(
        description="Scratch assay analysis using left-edge anchoring with time-0 box width."
    )
    parser.add_argument("--input", required=True, help="Input image folder")
    parser.add_argument("--output", required=True, help="Output results folder")
    parser.add_argument("--wound-geometry-mode", choices=["auto", "insert", "freehand"], default="auto")

    parser.add_argument("--blur-kernel", type=int, default=5)
    parser.add_argument("--background-kernel", type=int, default=101)
    parser.add_argument("--std-window", type=int, default=21)
    parser.add_argument("--residual-window", type=int, default=9)

    parser.add_argument("--corridor-smooth-window", type=int, default=31)
    parser.add_argument("--min-corridor-width", type=int, default=20)

    parser.add_argument("--threshold-mode", choices=["percentile", "otsu", "hybrid"], default="hybrid")
    parser.add_argument("--percentile-value", type=float, default=60.0)
    parser.add_argument("--min-open-object-size", type=int, default=100)
    parser.add_argument("--morph-close", type=int, default=5)
    parser.add_argument("--morph-open", type=int, default=3)

    parser.add_argument("--leading-edge-search-radius", type=int, default=120)
    parser.add_argument("--edge-smooth-window", type=int, default=21)
    parser.add_argument("--min-cell-run-width", type=int, default=12)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    df = analyze_folder(
        input_dir=Path(args.input),
        output_dir=Path(args.output),
        wound_geometry_mode=args.wound_geometry_mode,
        blur_kernel=args.blur_kernel,
        background_kernel=args.background_kernel,
        std_window=args.std_window,
        residual_window=args.residual_window,
        corridor_smooth_window=args.corridor_smooth_window,
        min_corridor_width=args.min_corridor_width,
        threshold_mode=args.threshold_mode,
        percentile_value=args.percentile_value,
        min_open_object_size=args.min_open_object_size,
        morph_close=args.morph_close,
        morph_open=args.morph_open,
        leading_edge_search_radius=args.leading_edge_search_radius,
        edge_smooth_window=args.edge_smooth_window,
        min_cell_run_width=args.min_cell_run_width
    )

    with pd.option_context("display.max_columns", None, "display.width", 260):
        print("\nPreview:")
        print(df.head())


if __name__ == "__main__":
    main()
