import gzip
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from packages.common.utils import DomainError
from packages.schemas.models import TrackFrame, TrackSummary
from packages.video.masks import bbox, encode_rle
from packages.video.processing import extract_shot

TRACK_SCHEMA = pa.schema([
    ("schema_version", pa.string()), ("video_id", pa.string()), ("shot_id", pa.string()),
    ("frame_index", pa.int64()), ("timestamp", pa.float64()), ("source_timestamp", pa.float64()),
    ("entity_id", pa.string()), ("track_id", pa.string()), ("provider_track_id", pa.string()),
    ("mask_ref", pa.string()), ("bbox_xyxy", pa.list_(pa.float64(), 4)),
    ("centroid", pa.list_(pa.float64(), 2)), ("centroid_normalized", pa.list_(pa.float64(), 2)),
    ("provider_confidence", pa.float64()), ("tracking_confidence", pa.float64()),
    ("observed", pa.bool_()), ("visibility", pa.string()), ("origin", pa.string()),
    ("identity_status", pa.string()), ("warnings", pa.list_(pa.string())), ("model_run_id", pa.string())])


def build_tracklets(records, entity, shot, manifest, frame_map, video_id, model_run_id, bundle_ref, correction=None):
    indexed = defaultdict(dict)
    for rec in records:
        frame = rec["frame"]
        if not 0 <= frame < shot.end_frame - shot.start_frame:
            raise DomainError("E_SAM_FRAME", "Provider frame outside shot")
        if rec["object_id"] in indexed[frame]:
            raise DomainError("E_SAM_DUPLICATE", "Duplicate frame/object provider record")
        indexed[frame][rec["object_id"]] = rec
    candidates = sorted({r["object_id"] for r in records}) or ["unmatched"]
    selected = correction.get("provider_track_id") if correction and correction["kind"] == "association" else None
    if selected is not None and selected not in candidates:
        raise DomainError("E_ASSOCIATION_INVALID", "Selected provider object was not found in this shot")
    if selected is not None:
        candidates = [selected]
    rows, masks, summaries = [], {}, []
    for candidate in candidates:
        ambiguous = len(candidates) > 1 and candidate != selected
        associated = not ambiguous and (len(candidates) == 1 or candidate == selected)
        segment = 0
        missing = 0
        seen = False
        previous_box = None
        track_rows = []
        for local in range(shot.end_frame - shot.start_frame):
            global_frame = shot.start_frame + local
            rec = indexed[local].get(candidate)
            warnings = []
            reappeared = bool(rec and seen and missing >= 3)
            if reappeared:
                segment += 1
                # A same provider ordinal is not proof of identity after full occlusion.
                associated = False
                warnings.append("Identity after missing run is unverified")
            track_id = f"{entity.entity_id}:{shot.shot_id}:{candidate}:{segment}"
            mask_ref = box = centroid = normalized = None
            if rec:
                mask = rec["mask"]
                if mask.shape != (manifest.height, manifest.width):
                    raise DomainError("E_SAM_COORDINATES", "Mask shape differs from normalized video")
                box = bbox(mask)
                if box is None:
                    rec = None
                else:
                    ys, xs = np.nonzero(mask)
                    centroid = [float(xs.mean()), float(ys.mean())]
                    normalized = [centroid[0] / manifest.width, centroid[1] / manifest.height]
                    mask_key = f"{global_frame}/{candidate}"
                    masks[mask_key] = encode_rle(mask)
                    mask_ref = f"{bundle_ref}#{mask_key}"
                    if previous_box:
                        area = (box[2] - box[0]) * (box[3] - box[1])
                        prior_area = (previous_box[2] - previous_box[0]) * (previous_box[3] - previous_box[1])
                        jump = np.linalg.norm(np.array(box[:2]) - np.array(previous_box[:2]))
                        if area / max(1, prior_area) > 2.5 or area / max(1, prior_area) < .4:
                            warnings.append("mask_area_jump")
                        if jump > .15 * max(manifest.width, manifest.height):
                            warnings.append("centroid_motion_jump")
                    previous_box = box
            if rec:
                seen, missing = True, 0
            else:
                missing += 1
            if ambiguous:
                warnings.append("Multiple candidates; semantic association needs review")
            row = TrackFrame(video_id=video_id, shot_id=shot.shot_id, frame_index=global_frame,
                timestamp=global_frame * manifest.fps_den / manifest.fps_num,
                source_timestamp=frame_map[global_frame]["source_timestamp"], entity_id=entity.entity_id,
                track_id=track_id, provider_track_id=candidate if candidate != "unmatched" else None,
                mask_ref=mask_ref, bbox_xyxy=box, centroid=centroid, centroid_normalized=normalized,
                provider_confidence=rec.get("confidence") if rec else None,
                tracking_confidence=(.65 if warnings else .9) if rec else None,
                observed=rec is not None, origin="measured" if rec else "missing",
                visibility=("CANDIDATE_REAPPEARANCE" if rec and not associated else "VISIBLE") if rec else "LOST",
                identity_status=("associated" if associated else "ambiguous" if ambiguous else "unverified") if rec else "lost",
                warnings=warnings, model_run_id=model_run_id)
            track_rows.append(row.model_dump(mode="json"))
        rows.extend(track_rows)
        for track in sorted({r["track_id"] for r in track_rows}):
            group = [r for r in track_rows if r["track_id"] == track]
            longest = run = 0
            for r in group:
                run = run + 1 if not r["observed"] else 0
                longest = max(longest, run)
            summaries.append(TrackSummary(entity_id=entity.entity_id, track_id=track,
                observed_frame_coverage=sum(r["observed"] for r in group) / len(group),
                missing_frames=sum(not r["observed"] for r in group), longest_missing_run=longest,
                reinitializations=1 if not track.endswith(":0") else 0,
                anomaly_count=sum(len(r["warnings"]) for r in group),
                identity_status="needs_review" if any(r["identity_status"] != "associated" for r in group) else "associated").model_dump())
    return rows, masks, summaries


def tracking(provider, video, manifest, plan, frame_map, output: Path, prefix, record, corrections):
    output.mkdir(parents=True, exist_ok=True)
    rows, summaries, refs, anchors = [], [], [], []
    for shot in manifest.shots:
        shot_file = output / f"{shot.shot_id}.mp4"
        extract_shot(video, shot_file, shot)
        for entity in plan.entities:
            relevant = [c for c in corrections if c["shot_id"] == shot.shot_id and c["entity_id"] == entity.entity_id]
            provider_corrections = [{**c, "frame_index": c["frame_index"] - shot.start_frame} for c in relevant]
            predictions = provider.track(shot_file, entity.sam_prompt, manifest.width, manifest.height, provider_corrections, record)
            name = f"masks_{shot.shot_id}_{entity.entity_id}.json.gz"
            ref = f"{prefix}/{name}"
            group, masks, stats = build_tracklets(predictions, entity, shot, manifest, frame_map,
                manifest.video_id, record.last_id, ref, next((c for c in relevant if c["kind"] == "association"), None))
            rows.extend(group)
            summaries.extend(stats)
            (output / name).write_bytes(gzip.compress(json.dumps(masks).encode(), mtime=0))
            refs.append(name)
            measured = [r for r in group if r["observed"]]
            if measured:
                sharpness = {d["frame_index"]: d["blur_laplacian"] for d in manifest.diagnostics["frames"]}
                best = max(measured, key=lambda r: sharpness.get(r["frame_index"], 0) * (r["bbox_xyxy"][2] - r["bbox_xyxy"][0]) * (r["bbox_xyxy"][3] - r["bbox_xyxy"][1]))
                anchors.append({"entity_id": entity.entity_id, "shot_id": shot.shot_id, "frame_index": best["frame_index"],
                                "mask_ref": best["mask_ref"], "method": "measured sharpness times visible bbox area; heuristic"})
        shot_file.unlink()
    pq.write_table(pa.Table.from_pylist(rows, schema=TRACK_SCHEMA), output / "tracks.parquet", compression="zstd")
    reasons = []
    for entity in plan.entities:
        group = [r for r in rows if r["entity_id"] == entity.entity_id]
        frames = {r["frame_index"] for r in group if r["observed"] and r["identity_status"] == "associated"}
        coverage = len(frames) / manifest.frame_count
        if coverage < .8:
            reasons.append(f"{entity.entity_id}: associated measured coverage {coverage:.1%} below heuristic 80% gate")
    if any(r["identity_status"] == "ambiguous" for r in rows):
        reasons.append("Ambiguous semantic-to-track association")
    if len(manifest.shots) > 1:
        reasons.append("Hard scene cuts: tracklets are shot-local; cross-shot identity unverified")
    report = {"schema_version": "0.1.0", "inference_mode": record.mode,
        "calibration": "uncalibrated heuristic; not provider probability", "summaries": summaries,
        "anchors": anchors, "review_reasons": reasons, "mask_bundles": refs,
        "reprojection": "not_evaluated", "physical_feasibility": "not_evaluated"}
    (output / "tracking_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
