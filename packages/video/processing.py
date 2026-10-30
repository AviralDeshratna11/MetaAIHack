import json
import subprocess
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from packages.common.config import settings
from packages.common.utils import DomainError, digest
from packages.schemas.models import Shot, VideoManifest


def command(args: list[str], timeout=180) -> str:
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, check=True)
        return result.stdout.decode("utf-8")
    except FileNotFoundError as exc:
        raise DomainError("E_TOOL_MISSING", f"Required executable unavailable: {args[0]}", 503) from exc
    except subprocess.TimeoutExpired as exc:
        raise DomainError("E_MEDIA_TIMEOUT", "Video processing timed out", 422) from exc
    except subprocess.CalledProcessError as exc:
        raise DomainError("E_MEDIA_INVALID", exc.stderr.decode("utf-8", errors="replace")[-1200:], 422) from exc


def probe(path: Path, check_duration=True) -> dict:
    cfg = settings()
    raw = json.loads(command([cfg.ffprobe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]))
    streams = [s for s in raw.get("streams", []) if s.get("codec_type") == "video"]
    if not streams:
        raise DomainError("E_MEDIA_INVALID", "No video stream found")
    stream = streams[0]
    duration = float(stream.get("duration") or raw["format"].get("duration") or 0)
    if not np.isfinite(duration) or duration <= 0:
        raise DomainError("E_MEDIA_INVALID", "Video duration is invalid")
    if check_duration and not cfg.min_duration <= duration <= cfg.max_duration:
        raise DomainError("E_DURATION_UNSUPPORTED", f"Supported duration: {cfg.min_duration}–{cfg.max_duration} seconds")
    rotation = next((d.get("rotation", 0) for d in stream.get("side_data_list", []) if "rotation" in d),
                    stream.get("tags", {}).get("rotate", 0))
    # Decode every source frame; this verifies actual decodability, not just container metadata.
    frames = json.loads(command([cfg.ffprobe, "-v", "error", "-select_streams", "v:0", "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time,pkt_duration_time", "-of", "json", str(path)]))["frames"]
    pts = [float(frame["best_effort_timestamp_time"]) for frame in frames if "best_effort_timestamp_time" in frame]
    if not pts or not np.all(np.isfinite(pts)) or np.any(np.diff(pts) < 0):
        raise DomainError("E_MEDIA_TIMELINE", "Missing, nonfinite, or non-monotonic source timestamps")
    return {"codec": stream["codec_name"], "width": stream["width"], "height": stream["height"],
            "duration_s": duration, "native_fps": stream.get("r_frame_rate"),
            "average_fps": stream.get("avg_frame_rate"), "time_base": stream.get("time_base"),
            "start_pts": stream.get("start_pts"), "start_time": pts[0], "rotation": int(rotation),
            "has_audio": any(s.get("codec_type") == "audio" for s in raw["streams"]),
            "source_pts": pts, "decoded_frames": len(pts)}


def source_mapping(source_pts: list[float], count: int, fps: int) -> list[dict]:
    pts = np.asarray(source_pts, dtype=np.float64)
    relative = pts - pts[0]
    # Corresponds to setpts=PTS-STARTPTS,fps=...:round=near (nonnegative PTS).
    ticks = np.floor(relative * fps + .5).astype(np.int64)
    indices = np.clip(np.searchsorted(ticks, np.arange(count), side="right") - 1, 0, len(pts) - 1)
    counts = Counter(indices.tolist())
    used = set(indices.tolist())
    return [{"frame_index": frame, "timestamp": frame / fps, "source_frame_index": int(index),
             "source_timestamp": float(pts[index]), "source_relative_timestamp": float(relative[index]),
             "mapping": "duplicated" if counts[int(index)] > 1 else "sampled",
             "source_frames_dropped_before": int(sum(j not in used for j in range(int(indices[frame - 1]) + 1, int(index)))) if frame else int(index)}
            for frame, index in enumerate(indices)]


def normalize(source: Path, output: Path, video_id: str, fps: int) -> VideoManifest:
    cfg = settings()
    output.mkdir(parents=True, exist_ok=True)
    original = probe(source)
    filters = f"setpts=PTS-STARTPTS,scale=w='min(1280,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2,fps={fps}:round=near:start_time=0"
    dest = output / "video_720p_15fps.mp4"
    command([cfg.ffmpeg, "-v", "error", "-i", str(source), "-map", "0:v:0", "-vf", filters,
             "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-movflags", "+faststart", "-y", str(dest)])
    if original["has_audio"]:
        command([cfg.ffmpeg, "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000",
                 "-y", str(output / "audio.wav")])
    cap = cv2.VideoCapture(str(dest))
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    diagnostics, candidates, cuts = [], {}, [0]
    previous_hist = previous_gray = None
    frame_index = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        small = cv2.resize(frame, (160, 90))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        hist = cv2.calcHist([small], [0, 1, 2], None, [8, 8, 8], [0, 256] * 3)
        cv2.normalize(hist, hist, norm_type=cv2.NORM_L1)
        cut_score = float(cv2.compareHist(hist, previous_hist, cv2.HISTCMP_BHATTACHARYYA)) if previous_hist is not None else 0.
        duplicate = bool(previous_gray is not None and np.abs(gray.astype(float) - previous_gray).mean() < .6)
        flow = cv2.calcOpticalFlowFarneback(previous_gray, gray, None, .5, 2, 9, 2, 5, 1.1, 0) if previous_gray is not None else None
        motion = float(np.linalg.norm(flow, axis=2).mean()) if flow is not None else 0.
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        diagnostics.append({"frame_index": frame_index, "blur_laplacian": sharpness,
                            "brightness": float(gray.mean()), "duplicate": duplicate,
                            "camera_motion_proxy": motion, "cut_score": cut_score})
        if cut_score > .65 and frame_index - cuts[-1] >= max(2, fps // 2):
            cuts.append(frame_index)
        group = (len(cuts) - 1, frame_index // (fps * 2))
        if group not in candidates or sharpness > candidates[group][0]:
            candidates[group] = (sharpness, frame_index, frame.copy())
        previous_hist, previous_gray = hist, gray
        frame_index += 1
    cap.release()
    if not frame_index:
        raise DomainError("E_MEDIA_INVALID", "Normalized video decoded no frames")
    mapping = source_mapping(original["source_pts"], frame_index, fps)
    sampled = {row["source_frame_index"] for row in mapping}
    dropped = [i for i in range(len(original["source_pts"])) if i not in sampled]
    pq.write_table(pa.Table.from_pylist(mapping), output / "frame_map.parquet")
    cuts.append(frame_index)
    shots = [Shot(shot_id=f"shot_{i:03}", start_frame=a, end_frame=b) for i, (a, b) in enumerate(zip(cuts, cuts[1:]))]
    keyframes = []
    for _, index, image in candidates.values():
        ref = f"keyframe_{index:06}.jpg"
        cv2.imwrite(str(output / ref), image)
        keyframes.append(ref)
    original.pop("source_pts")
    manifest = VideoManifest(video_id=video_id, original=original, normalized_ref=dest.name,
        width=width, height=height, fps_num=fps, frame_count=frame_index, duration_s=frame_index / fps,
        normalization_hash=digest({"filters": filters, "codec": "libx264", "crf": 20}),
        frame_map_ref="frame_map.parquet", shots=shots, keyframe_refs=keyframes,
        diagnostics={"calibration": "uncalibrated heuristics", "cut_threshold": .65,
                     "duplicate_threshold": .6, "dropped_source_frame_indices": dropped,
                     "duplicated_output_frame_count": sum(row["mapping"] == "duplicated" for row in mapping),
                     "frames": diagnostics})
    (output / "manifest.json").write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
    (output / "shots.json").write_text(json.dumps([s.model_dump() for s in shots], indent=2), encoding="utf-8")
    return manifest


def extract_shot(video: Path, dest: Path, shot: Shot):
    command([settings().ffmpeg, "-v", "error", "-i", str(video), "-vf",
             f"trim=start_frame={shot.start_frame}:end_frame={shot.end_frame},setpts=PTS-STARTPTS",
             "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-y", str(dest)])

