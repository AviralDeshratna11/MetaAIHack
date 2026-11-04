"""Shared-frame alignment of independently inferred VGGT window gauges.

Correspondences are pixels of the exact same reference image, not tracked dynamic
points across time. Residual checks test cross-window consistency, not accuracy.
"""
import numpy as np

from packages.geometry.math3d import align_similarity


def frame_windows(indices, capacity=4):
    indices = sorted(set(indices))
    if capacity < 2:
        raise ValueError("Window capacity must include an anchor and new frame")
    if len(indices) <= capacity:
        return [indices] if indices else []
    return [[indices[0], *indices[i:i+capacity-1]] for i in range(1, len(indices), capacity-1)]


def align_window(source, target, max_relative_rmse=.06):
    valid = np.isfinite(source).all(2) & np.isfinite(target).all(2)
    a, b = source[valid], target[valid]
    if len(a) < 64:
        raise ValueError("Insufficient shared-frame geometry for window alignment")
    ids = np.linspace(0, len(a)-1, min(len(a), 4096), dtype=int)
    a, b = a[ids], b[ids]
    # Freeze a robust correspondence subset; re-fit and retain the residual.
    for _ in range(3):
        scale, rotation, translation, _ = align_similarity(a, b)
        errors = np.linalg.norm(scale*a@rotation.T+translation-b, axis=1)
        keep = errors <= np.quantile(errors, .9)
        if keep.all(): break
        a, b = a[keep], b[keep]
    scale, rotation, translation, rmse = align_similarity(a, b)
    extent = float(np.linalg.norm(np.ptp(b, axis=0)))
    relative = rmse / max(extent, 1e-12)
    if not np.isfinite(relative) or relative > max_relative_rmse:
        raise ValueError(f"Shared-frame window alignment failed: relative RMSE {relative:.6f}")
    return scale, rotation, translation, {"scale": scale, "rotation": rotation.tolist(),
        "translation": translation.tolist(), "rmse": rmse, "relative_rmse": relative,
        "correspondence_count": len(a), "independent_accuracy": False}
