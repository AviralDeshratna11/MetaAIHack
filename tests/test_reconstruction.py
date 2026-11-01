import gzip
import json
import shutil

import numpy as np
import pyarrow.parquet as pq
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from packages.common.config import settings
from packages.common.utils import DomainError
from packages.geometry.math3d import (align_similarity, matrix_quaternion, quaternion_matrix, project,
    transform_points, unproject)
from packages.geometry.providers import provider_fingerprint
from packages.geometry.tables import write_contracts
from packages.meta_client.fixture import fixture_plan
from packages.schemas.models import Shot, VideoManifest
from packages.schemas.reconstruction import (CameraFrame, ContactFrame, Pose3D, PoseFrame, ReconstructionConfig,
    ReconstructionRequest)
from workers.geometry.reconstruct import MaskReader, reconstruct, relative_rows, sample_frames
from workers.interaction.fusion import fuse_interactions, refine_actions


def config(**changes):
    return ReconstructionConfig(**changes).model_dump()


def manifest(count=12):
    return VideoManifest(video_id="vid", original={}, normalized_ref="video.mp4", width=40, height=20,
        fps_num=10, frame_count=count, duration_s=count/10, normalization_hash="hash", frame_map_ref="map",
        shots=[Shot(shot_id="shot", start_frame=0, end_frame=count)], keyframe_refs=[], diagnostics={})


def pose(entity, frame, position, quaternion=None):
    return PoseFrame(video_id="vid", shot_id="shot", frame_index=frame, timestamp=frame/10, entity_id=entity,
        track_id=entity+":0", world_frame="world:vid:shot", pose=Pose3D(position_xyz=position,
        quaternion_xyzw=quaternion), points_world=[position], origin="synthetic", representation="surface_centroid",
        source="synthetic-test").model_dump(mode="json")


def test_known_similarity_alignment_and_transform_chain():
    points = np.random.default_rng(42).normal(size=(40, 3))
    rotation = quaternion_matrix([0, 0, np.sin(.3), np.cos(.3)])
    target = 2.3 * points @ rotation.T + [1, -2, 4]
    scale, fitted, translation, rmse = align_similarity(points, target)
    assert scale == pytest.approx(2.3)
    assert np.allclose(fitted, rotation)
    assert np.allclose(translation, [1, -2, 4]) and rmse < 1e-10
    assert np.allclose(quaternion_matrix(matrix_quaternion(rotation)), rotation)


def test_degenerate_alignment_and_nonunit_quaternion_are_rejected():
    with pytest.raises(ValueError): align_similarity(np.zeros((5, 3)), np.zeros((5, 3)))
    with pytest.raises(ValidationError): Pose3D(position_xyz=[0, 0, 0], quaternion_xyzw=[0, 0, 0, 2])
    with pytest.raises(ValidationError): ReconstructionConfig(contact_on=.3, contact_off=.5)
    with pytest.raises(ValidationError): Pose3D(position_xyz=[float("nan"), 0, 0])


def test_projection_unprojection_roundtrip_with_moving_camera():
    depth = np.ones((10, 20)) * 2
    k = np.array([[20, 0, 10], [0, 20, 5], [0, 0, 1.]])
    transform = np.eye(4)
    transform[:3, :3] = quaternion_matrix([0, np.sin(.2), 0, np.cos(.2)])
    transform[:3, 3] = [1, 2, 3]
    points = unproject(depth, k, transform)
    uv = project(points.reshape(-1, 3), k, transform)
    y, x = np.indices(depth.shape)
    assert np.allclose(uv, np.stack([x, y], -1).reshape(-1, 2))


def test_gpu_preprocessing_records_exact_pixel_center_mapping_without_crop():
    from workers.geometry.gpu_entry import preprocess
    image = np.zeros((360, 640, 3), np.uint8)
    padded, affine, (left, top, width, height) = preprocess(image)
    assert padded.shape == (518, 518, 3)
    assert width <= 518 and height <= 518 and width % 14 == height % 14 == 0
    center = affine @ [319.5, 179.5, 1]
    assert np.allclose(center[:2], [left+(width-1)/2, top+(height-1)/2])
    k = np.array([[640, 0, 319.5], [0, 640, 179.5], [0, 0, 1.]])
    assert np.allclose(np.linalg.inv(affine) @ (affine @ k), k)


def test_object_frame_rotation_and_unknown_orientation_are_explicit():
    q = [0, 0, np.sin(np.pi/4), np.cos(np.pi/4)]
    hand = pose("hand", 0, [1, 1, 0])
    obj = pose("mug", 0, [1, 0, 0], q)
    row, = relative_rows([hand], [obj])
    assert np.allclose(row["hand_in_object"]["position_xyz"], [1, 0, 0])
    assert row["hand_in_object"]["quaternion_xyzw"] is None
    obj["pose"]["quaternion_xyzw"] = None
    row, = relative_rows([hand], [obj])
    assert row["hand_in_object"] is None
    assert row["relative_position_world_xyz"] == [0, 1, 0]


def test_typed_parquet_roundtrips_all_missing_geometry(tmp_path):
    row = pose("hand", 0, [0, 0, 1])
    row.update(pose=None, origin="missing", points_world=[])
    write_contracts(tmp_path / "poses.parquet", PoseFrame, [row])
    saved, = pq.read_table(tmp_path / "poses.parquet").to_pylist()
    assert saved["pose"] is None and PoseFrame.model_validate(saved).origin == "missing"
    schema = pq.read_schema(tmp_path / "poses.parquet")
    assert schema.field("pose").type.num_fields > 1


def test_sampling_never_crosses_shots_and_respects_explicit_budget():
    video = manifest(100)
    video.shots = [Shot(shot_id="a", start_frame=0, end_frame=50), Shot(shot_id="b", start_frame=50, end_frame=100)]
    frames = sample_frames(video, fixture_plan(10), config(max_frames_per_shot=8))
    assert {0, 49, 50, 99} <= set(frames)
    assert len(frames) <= 16
    with pytest.raises(DomainError) as exc:
        sample_frames(video, fixture_plan(10), config(max_frames_per_shot=8, max_total_frames=4))
    assert exc.value.code == "E_GEOMETRY_BUDGET"


def contact_inputs(count=12, missing_geometry=()):
    tracks, hands, objects, mask_map = [], [], [], {}
    for frame in range(count):
        for entity in ("hand", "mug"):
            key = f"{entity}:{frame}"
            mask = np.zeros((20, 40), np.uint8)
            mask[5:9, frame:frame+4] = 1
            mask_map[key] = mask
            tracks.append({"frame_index": frame, "entity_id": entity, "observed": True, "identity_status": "associated",
                "track_id": entity+":0", "mask_ref": key, "centroid": [frame+1.5, 6.5]})
        if frame not in missing_geometry:
            hands.append(pose("hand", frame, [frame*.01, 0, 1], [0, 0, 0, 1]))
            objects.append(pose("mug", frame, [frame*.01, 0, 1], [0, 0, 0, 1]))
    return tracks, hands, objects, mask_map.__getitem__


def test_semantic_contact_and_mask_overlap_alone_do_not_establish_3d_contact(tmp_path):
    video = manifest()
    plan = fixture_plan(video.duration_s)
    tracks, _, _, masks = contact_inputs()
    report = fuse_interactions(video, plan, tracks, masks, [], [], tmp_path, config(), "fixture")
    rows = pq.read_table(tmp_path / "contacts.parquet").to_pylist()
    assert all(row["state"] != "CONTACT" for row in rows)
    assert report["contact_events"] == 0


def test_persistence_suppresses_single_frame_spikes_and_missing_geometry_does_not_release(tmp_path):
    video = manifest()
    tracks, hands, objects, masks = contact_inputs(missing_geometry=range(5, 11))
    cfg = config(contact_on=.65, persistence_frames=3)
    fuse_interactions(video, fixture_plan(video.duration_s), tracks, masks, hands, objects, tmp_path, cfg, "fixture")
    events = json.loads((tmp_path / "interaction_events.json").read_text())
    assert any(e["kind"] == "contact_on" for e in events)
    assert not any(e["kind"] == "contact_off" for e in events)
    assert all(not e["validated_grasp"] for e in events)
    first = next(e for e in events if e["kind"] == "contact_on")
    assert first["frame_index"] >= 2


def test_unknown_identity_breaks_contact_continuity(tmp_path):
    tracks, hands, objects, masks = contact_inputs()
    for row in tracks:
        if row["frame_index"] == 4: row["identity_status"] = "unverified"
    fuse_interactions(manifest(), fixture_plan(1.2), tracks, masks, hands, objects, tmp_path,
        config(contact_on=.65), "fixture")
    rows = pq.read_table(tmp_path / "contacts.parquet").to_pylist()
    assert all(r["state"] == "UNKNOWN" for r in rows if r["frame_index"] == 4)
    assert all(r["state"] != "CONTACT" for r in rows if r["frame_index"] == 5)


def test_holding_one_geometry_spike_does_not_manufacture_persistence(tmp_path):
    tracks, hands, objects, masks = contact_inputs(missing_geometry=[i for i in range(12) if i != 5])
    report = fuse_interactions(manifest(), fixture_plan(1.2), tracks, masks, hands, objects, tmp_path,
        config(contact_on=.65), "fixture")
    assert report["contact_frames"] == 0 and report["contact_events"] == 0


def test_refinement_is_bounded_and_does_not_overwrite_semantic_plan():
    plan = fixture_plan(12)
    original = plan.model_dump_json()
    grasp = plan.actions[1]
    event = {"event_id": "event", "kind": "grasp_candidate", "object_id": "mug", "hand_id": "hand", "timestamp": grasp.start_s+.1}
    refined = refine_actions(plan, [event], 1.5)
    assert refined[1]["refined_start_s"] == pytest.approx(grasp.start_s+.1)
    assert refined[1]["timing_source"] == "contact_candidate"
    assert plan.model_dump_json() == original
    assert refine_actions(plan, [{**event, "timestamp": 100}], 1.5)[1]["refined_start_s"] is None


def test_missing_gpu_runtime_fails_with_actionable_configuration():
    with pytest.raises(DomainError) as exc: provider_fingerprint(config(backend="vggt"))
    assert exc.value.code == "E_GEOMETRY_CONFIG"


@pytest.mark.skipif(not shutil.which(settings().ffmpeg) or not shutil.which(settings().ffprobe), reason="FFmpeg required")
def test_real_media_to_geometry_contact_and_itr_contract(tmp_path, monkeypatch):
    from scripts.make_fixtures import make_video
    from packages.meta_client.fixture import FixtureProvider
    from packages.video.processing import normalize
    from workers.perception.tracking import tracking
    monkeypatch.setattr(settings(), "min_duration", .01)
    source = tmp_path / "source.mp4"
    make_video(source, seconds=2)
    normalized, perception, geometry, interaction = [tmp_path / s for s in ("normalized", "perception", "geometry", "interaction")]
    video = normalize(source, normalized, "vid", 15)
    plan = fixture_plan(video.duration_s)
    mapping = pq.read_table(normalized / "frame_map.parquet").to_pylist()
    class Recorder:
        last_id = "fixture"
        mode = "fixture"
        def __call__(self, event): pass
    tracking(FixtureProvider(), normalized / video.normalized_ref, video, plan, mapping,
        perception, str(perception), Recorder(), [])
    tracks = pq.read_table(perception / "tracks.parquet").to_pylist()
    masks = MaskReader(lambda key: __import__("pathlib").Path(key).read_bytes())
    report = reconstruct(normalized / video.normalized_ref, video, plan, tracks, masks, geometry,
        config(max_frames_per_shot=8), "source-run", "fixture")
    hands = pq.read_table(geometry / "hand_pose.parquet").to_pylist()
    objects = pq.read_table(geometry / "object_pose.parquet").to_pylist()
    assert report.camera_frames == 8 and report.hand_pose_frames > 0
    assert len(hands) == video.frame_count and len(objects) == 2*video.frame_count
    assert any(r["origin"] == "missing" for r in hands)
    assert all(PoseFrame.model_validate(r) for r in hands+objects)
    fuse_interactions(video, plan, tracks, masks, hands, objects, interaction, config(), "fixture")
    assert all(ContactFrame.model_validate(r) for r in pq.read_table(interaction / "contacts.parquet").to_pylist())


def test_reconstruction_api_requires_a_valid_source_and_exposes_contract(database):
    from apps.api.main import app
    with TestClient(app) as client:
        response = client.post("/v1/videos/missing/reconstruct", json={"source_job_id": "missing", "idempotency_key": "test"})
        assert response.status_code == 404
        spec = client.get("/openapi.json").json()
        assert "GeometryWindow" in spec["components"]["schemas"]
        assert "/v1/videos/{video_id}/contacts" in spec["paths"]
