import numpy as np


def encode_rle(mask: np.ndarray) -> dict:
    """Uncompressed row-major RLE v1; starts with a run of zero pixels."""
    if mask.ndim != 2:
        raise ValueError("Mask must be 2D")
    flat = (mask > 0).astype(np.uint8).ravel()
    boundaries = np.flatnonzero(np.diff(np.r_[0, flat, 0]))
    counts = np.diff(np.r_[0, boundaries, len(flat)]).tolist()
    # Alternating runs can end with zero length; valid and deterministic.
    return {"encoding": "row-major-rle-v1", "height": mask.shape[0], "width": mask.shape[1], "counts": counts}


def decode_rle(data: dict) -> np.ndarray:
    if data.get("encoding") != "row-major-rle-v1":
        raise ValueError("Unknown mask encoding")
    h, w, counts = data["height"], data["width"], data["counts"]
    if h <= 0 or w <= 0 or h * w > 100_000_000 or any(type(c) is not int or c < 0 for c in counts) or sum(counts) != h * w:
        raise ValueError("Invalid RLE dimensions or runs")
    return np.repeat(np.arange(len(counts), dtype=np.uint8) % 2, counts).reshape(h, w)


def bbox(mask):
    ys, xs = np.nonzero(mask)
    return [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1] if len(xs) else None

