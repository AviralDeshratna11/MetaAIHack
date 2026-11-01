import gzip
import json
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq

from packages.common.utils import DomainError
from packages.geometry.math3d import (align_similarity, finite_difference, matrix_pose, matrix_quaternion,
    pose_matrix, principal_rotation, project, transform_points)
from packages.geometry.providers import FixtureGeometry, LocalGeometry, provider_fingerprint
from packages.geometry.tables import write_contracts
from packages.schemas.reconstruction import Alignment, CameraFrame, Pose3D, PoseFrame, RelativeFrame, ReconstructionReport
from packages.video.masks import decode_rle


class MaskReader:
    def __init__(self, read):
        self.read, self.cache = read, {}

    def __call__(self, reference):
        key, fragment = reference.split("#", 1)
        if key not in self.cache:
            # Keep a bounded number of shot/entity bundles in memory.
            if len(self.cache) >= 8:
                self.cache.pop(next(iter(self.cache)))
            self.cache[key] = json.loads(gzip.decompress(self.read(key)))
        return decode_rle(self.cache[key][fragment])


def sample_frames(manifest, plan, config):
    selected = set()
    for shot in manifest.shots:
        mandatory = {shot.start_frame, shot.end_frame - 1}
        priority = set(mandatory)
        fps = manifest.fps_num / manifest.fps_den
        for action in plan.actions:
            for time in (action.start_s, action.end_s):
                for offset in (-.2, 0, .2):
                    index = round((time + offset) * fps)
                    if shot.start_frame <= index < shot.end_frame:
                        priority.add(index)
        cap = config["max_frames_per_shot"]
        candidates = sorted(priority - mandatory)
        if len(priority) > cap:
            candidates = [candidates[i] for i in np.linspace(0, len(candidates)-1, cap-len(mandatory), dtype=int)]
        chosen = mandatory | set(candidates)
        regular = sorted(set(range(shot.start_frame, shot.end_frame, max(1, round(fps/config["sample_fps"])))) - chosen)
        count = min(cap - len(chosen), len(regular))
        if count:
            chosen.update(regular[i] for i in np.linspace(0, len(regular)-1, count, dtype=int))
        selected.update(chosen)
    if len(selected) > config["max_total_frames"]:
        raise DomainError("E_GEOMETRY_BUDGET", "Sampling exceeds max_total_frames; increase the explicit budget or lower per-shot sampling")
    return sorted(selected)


def selected_tracks(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[(row["frame_index"], row["entity_id"])].append(row)
    # Never arbitrarily select one candidate when semantic association is ambiguous.
    return {key: values[0] for key, values in groups.items() if len(values) == 1
            and values[0]["observed"] and values[0]["identity_status"] == "associated"}


def body_hand(packet, entity, mask, frame_id, world_frame, max_rmse):
    candidates = []
    points = packet["points"]
    h, w = mask.shape
    for person in packet["body"]:
        xy, xyz = np.asarray(person["keypoints_2d"]), np.asarray(person["keypoints_3d"])
        if xy.shape != (len(person["names"]), 2) or xyz.shape != (len(xy), 3):
            continue
        valid = np.isfinite(xy).all(1) & np.isfinite(xyz).all(1)
        valid &= (xy[:, 0] >= 0) & (xy[:, 0] < w) & (xy[:, 1] >= 0) & (xy[:, 1] < h)
        ids = np.flatnonzero(valid)
        if len(ids) < 6:
            continue
        pixels = xy[ids].astype(int)
        target = points[pixels[:, 1], pixels[:, 0]]
        good = np.isfinite(target).all(1)
        ids, target = ids[good], target[good]
        if len(ids) < 6:
            continue
        try:
            scale, rotation, translation, rmse = align_similarity(xyz[ids], target)
        except ValueError:
            continue
        extent = np.linalg.norm(np.ptp(target, axis=0))
        if extent <= 1e-8 or rmse / extent > max_rmse:
            continue
        world = scale * xyz @ rotation.T + translation
        for side in ("left", "right"):
            if entity.handedness not in ("unknown", side):
                continue
            names = person["names"]
            wrist_name = f"{side}-wrist"
            if wrist_name not in names:
                continue
            wrist = names.index(wrist_name)
            hand_ids = [i for i, name in enumerate(names) if name.startswith(side + "-") and any(
                part in name for part in ("wrist", "thumb", "index", "middle", "ring", "pinky"))]
            pixels = xy[hand_ids].astype(int)
            inside = (pixels[:, 0] >= 0) & (pixels[:, 0] < w) & (pixels[:, 1] >= 0) & (pixels[:, 1] < h)
            if not inside.any():
                continue
            # Require several projected hand joints to overlap the measured hand mask.
            valid_pixels = pixels[inside]
            overlap = mask[valid_pixels[:, 1], valid_pixels[:, 0]].mean()
            if overlap < .3:
                continue
            alignment = Alignment(alignment_id=f"body-{frame_id}-{entity.entity_id}-{side}",
                source_frame=f"sam3d:{frame_id}:{side}", target_frame=world_frame, rotation=rotation.tolist(),
                translation=translation.tolist(), scale=scale, rmse=rmse, correspondence_count=len(ids),
                method="per-frame Sim(3) fit: body keypoints to VGGT depth at projected joints; surface/skeleton bias possible")
            candidates.append((world[wrist], [names[i] for i in hand_ids], world[hand_ids], alignment))
    return candidates[0] if len(candidates) == 1 else None


def relative_rows(hands, objects):
    object_map = defaultdict(list)
    for row in objects:
        object_map[(row["shot_id"], row["frame_index"])].append(row)
    rows, previous = [], {}
    for hand in hands:
        for obj in object_map[(hand["shot_id"], hand["frame_index"])]:
            hp, op = hand["pose"], obj["pose"]
            relative = None
            hand_object = delta = None
            if hp and op:
                relative = (np.asarray(hp["position_xyz"]) - op["position_xyz"]).tolist()
                ot, ht = pose_matrix(op), pose_matrix(hp)
                if ot is not None:
                    position = transform_points([hp["position_xyz"]], np.linalg.inv(ot))[0].tolist()
                    hand_object = {"position_xyz": position, "quaternion_xyzw": None}
                    if ht is not None:
                        hand_object = matrix_pose(np.linalg.inv(ot) @ ht)
                key = (obj["shot_id"], obj["track_id"], hand["track_id"])
                prior = previous.get(key)
                if ot is not None and prior is not None:
                    delta = matrix_pose(np.linalg.inv(prior) @ ot)
                previous[key] = ot
            rows.append(RelativeFrame(shot_id=hand["shot_id"], frame_index=hand["frame_index"], timestamp=hand["timestamp"],
                world_frame=hand["world_frame"], hand_id=hand["entity_id"], object_id=obj["entity_id"],
                hand_track_id=hand["track_id"], object_track_id=obj["track_id"], hand_in_object=hand_object,
                relative_position_world_xyz=relative, object_delta=delta,
                origin=hand["origin"] if relative is not None else "missing",
                warnings=[] if hand_object else ["Object orientation unknown; only world-axis relative translation is available"]).model_dump(mode="json"))
    return rows


def reconstruct(video, manifest, plan, tracks, masks, output, config, source_run_id, mode):
    output.mkdir(parents=True, exist_ok=True)
    fingerprint = provider_fingerprint(config)
    if fingerprint != config.get("provider_fingerprint", fingerprint):
        raise DomainError("E_GEOMETRY_CHECKPOINT_CHANGED", "Geometry checkpoints changed after submission; submit a new run")
    if config["backend"] == "fixture" and mode != "fixture":
        raise DomainError("E_GEOMETRY_MODE", "Synthetic geometry cannot run on live perception")
    provider = FixtureGeometry() if config["backend"] == "fixture" else LocalGeometry()
    sampled, selected = sample_frames(manifest, plan, config), selected_tracks(tracks)
    cameras, hands, objects, alignments = [], [], [], []
    reasons = ["Monocular scale is relative; metric scale has no validated anchor"]
    if mode == "fixture": reasons.append("Synthetic geometry and contacts; not model evidence")
    if config["body_backend"] == "none" and mode != "fixture":
        reasons.append("SAM 3D Body disabled: hand surface centroids are not anatomical wrist poses")
    if mode != "fixture":
        reasons.append("VGGT scene/depth estimates and dynamic-object PCA poses require real-video reprojection review")
    cap = cv2.VideoCapture(str(video))
    previous = {}
    for shot in manifest.shots:
        world_frame = f"world:{manifest.video_id}:{shot.shot_id}"
        shot_dir = output / shot.shot_id
        shot_dir.mkdir()
        frame_paths = {}
        for index in sampled:
            if shot.start_frame <= index < shot.end_frame:
                cap.set(cv2.CAP_PROP_POS_FRAMES, index)
                ok, image = cap.read()
                if not ok: raise DomainError("E_GEOMETRY_MEDIA", f"Cannot decode canonical frame {index}")
                path = shot_dir / f"frame_{index}.jpg"
                cv2.imwrite(str(path), image)
                frame_paths[index] = path
        packets = provider.reconstruct(frame_paths, manifest, shot_dir, config)
        for index, packet in packets.items():
            camera = CameraFrame(video_id=manifest.video_id, shot_id=shot.shot_id, frame_index=index,
                timestamp=index * manifest.fps_den / manifest.fps_num, world_frame=world_frame,
                intrinsic=packet["intrinsic"].tolist(), world_from_camera=packet["world_from_camera"].tolist(),
                image_width=manifest.width, image_height=manifest.height, source=provider.name,
                origin="synthetic" if mode == "fixture" else "estimated")
            cameras.append(camera.model_dump(mode="json"))
        # Preserve the full canonical timeline: unsampled geometry is explicitly missing.
        for index in range(shot.start_frame, shot.end_frame):
            packet = packets.get(index)
            for entity in plan.entities:
                track = selected.get((index, entity.entity_id))
                row = PoseFrame(video_id=manifest.video_id, shot_id=shot.shot_id, frame_index=index,
                    timestamp=index * manifest.fps_den / manifest.fps_num, entity_id=entity.entity_id,
                    track_id=track["track_id"] if track else f"unresolved:{entity.entity_id}:{shot.shot_id}",
                    world_frame=world_frame, origin="missing", representation="missing", source=provider.name)
                if packet is not None and track is not None:
                    mask = masks(track["mask_ref"]).astype(bool)
                    if mask.shape != packet["points"].shape[:2]:
                        raise DomainError("E_GEOMETRY_COORDINATES", "Mask/point-map coordinate mismatch")
                    valid = mask & np.isfinite(packet["points"]).all(2) & np.isfinite(packet["confidence"]) & (packet["confidence"] > 0)
                    pts = packet["points"][valid]
                    if len(pts) >= 8:
                        median = np.median(pts, axis=0)
                        distance = np.linalg.norm(pts-median, axis=1)
                        pts = pts[distance <= np.quantile(distance, .95)]
                        pts = pts[np.linspace(0, len(pts)-1, min(len(pts), config["max_points_per_entity"]), dtype=int)]
                        position, rotation, representation = pts.mean(0), None, "surface_centroid"
                        if entity.role != "actor":
                            rotation = principal_rotation(pts, previous.get((shot.shot_id, track["track_id"]), {}).get("rotation"))
                            if rotation is None: row.warnings.append("Symmetry or insufficient geometry: rigid orientation unobserved")
                            else: row.warnings.append("Surface PCA orientation is a hypothesis, not calibrated 6D object pose")
                        elif config["body_backend"] == "sam3d":
                            result = body_hand(packet, entity, mask, index, world_frame, config["max_alignment_relative_rmse"])
                            if result:
                                position, names, keypoints, alignment = result
                                row.keypoint_names, row.keypoints_world = names, keypoints.tolist()
                                row.alignment_id = alignment.alignment_id
                                alignments.append(alignment.model_dump(mode="json"))
                                representation = "wrist"
                            else: row.warnings.append("No uniquely associated and aligned body wrist; using hand surface centroid")
                        if mode == "fixture": rotation = np.eye(3)
                        row.pose = Pose3D(position_xyz=position.tolist(), quaternion_xyzw=matrix_quaternion(rotation) if rotation is not None else None)
                        row.points_world = pts.tolist()
                        row.origin, row.representation = ("synthetic" if mode == "fixture" else "estimated"), representation
                        row.orientation_status = "synthetic" if mode == "fixture" else "pca_hypothesis" if rotation is not None else "unknown"
                        uv = project([position], packet["intrinsic"], packet["world_from_camera"])[0]
                        if np.isfinite(uv).all():
                            row.projected_centroid = uv.tolist()
                            row.reprojection_error_px = float(np.linalg.norm(uv - track["centroid"]))
                        key = (shot.shot_id, track["track_id"])
                        prior = previous.get(key)
                        if prior:
                            row.linear_velocity = finite_difference(position, prior["position"], row.timestamp-prior["timestamp"])
                            if rotation is not None and prior["rotation"] is not None:
                                rv = cv2.Rodrigues(prior["rotation"].T @ rotation)[0].ravel()
                                row.angular_velocity = (prior["rotation"] @ rv / (row.timestamp-prior["timestamp"])).tolist()
                        previous[key] = {"rotation": rotation, "position": position, "timestamp": row.timestamp}
                (hands if entity.role == "actor" else objects).append(row.model_dump(mode="json"))
        # Keep only reconstruction arrays/logs; images are temporary model inputs.
        for path in frame_paths.values(): path.unlink()
        (shot_dir / "gpu_request.json").unlink(missing_ok=True)
    cap.release()
    hands = write_contracts(output / "hand_pose.parquet", PoseFrame, hands)
    objects = write_contracts(output / "object_pose.parquet", PoseFrame, objects)
    write_contracts(output / "cameras.parquet", CameraFrame, cameras)
    relative = write_contracts(output / "object_centric.parquet", RelativeFrame, relative_rows(hands, objects))
    (output / "alignments.json").write_text(json.dumps(alignments, indent=2), encoding="utf-8")
    if len(manifest.shots) > 1: reasons.append("Shot-local worlds are independent; cross-cut alignment is unverified")
    if any(r["pose"] is not None and r["representation"] != "wrist" for r in hands) and mode != "fixture":
        reasons.append("Some hand estimates are surface centroids rather than anatomical wrists")
    if any(r["pose"] and r["pose"]["quaternion_xyzw"] is None for r in objects):
        reasons.append("Some object orientations are unknown; complete SE(3) trajectories unavailable")
    errors = [r["reprojection_error_px"] for r in hands+objects if r["reprojection_error_px"] is not None]
    report = ReconstructionReport(source_run_id=source_run_id, backend=provider.name, inference_mode=mode,
        world_frames=[f"world:{manifest.video_id}:{s.shot_id}" for s in manifest.shots], sampled_frames=sampled,
        camera_frames=len(cameras), hand_pose_frames=sum(r["pose"] is not None for r in hands),
        object_pose_frames=sum(r["pose"] is not None for r in objects),
        relative_pose_frames=sum(r["hand_in_object"] is not None for r in relative),
        reprojection_median_px=float(np.median(errors)) if errors else None, review_reasons=reasons)
    (output / "geometry_report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    (output / "geometry_provenance.json").write_text(json.dumps({"provider": fingerprint,
        "config": {k: v for k, v in config.items() if k not in ("gpu_python", "vggt_checkpoint", "body_checkpoint", "body_mhr")},
        "sampling": "canonical frame indices; no interpolated geometry; separate reconstruction per shot"}, indent=2), encoding="utf-8")
    return report
