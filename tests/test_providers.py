import json

import httpx
import numpy as np
import pytest

from packages.common.utils import DomainError
from packages.meta_client.fixture import fixture_plan
from packages.meta_client.live import LiveProvider, parse_sam_text, sam_records
from workers.semantic.parser import parse_semantics


class Log:
    def __init__(self): self.events = []
    def __call__(self, event): self.events.append(event)
    def lookup(self, key): return None


def provider(handler):
    return LiveProvider(httpx.Client(base_url="https://test.invalid/v1/", transport=httpx.MockTransport(handler)))


def test_auth_failure_is_not_retried():
    requests = []
    p = provider(lambda r: requests.append(r) or httpx.Response(401))
    log = Log()
    with pytest.raises(DomainError, match="rejected"):
        p.request("responses", model="test", key="key", record=log, json={})
    assert len(requests) == 1
    assert log.events[-1]["status"] == "failed"


def test_retry_is_bounded_and_honors_retry_after(monkeypatch):
    delays, requests = [], []
    monkeypatch.setattr("packages.meta_client.live.time.sleep", delays.append)
    p = provider(lambda r: requests.append(r) or httpx.Response(429, headers={"Retry-After": "0.25"}))
    with pytest.raises(DomainError, match="three attempts"):
        p.request("responses", model="test", key="key", record=Log(), json={})
    assert len(requests) == 3 and delays == [.25, .25]


def test_read_timeout_is_unknown_outcome_not_replayed():
    log = Log()
    def fail(request): raise httpx.ReadTimeout("unknown", request=request)
    p = provider(fail)
    with pytest.raises(DomainError) as exc:
        p.request("responses", model="test", key="key", record=log, json={})
    assert exc.value.code == "E_PROVIDER_OUTCOME_UNKNOWN"
    assert [e["status"] for e in log.events] == ["started", "unknown"]


def test_completed_provider_response_is_reused():
    class Cached(Log):
        def lookup(self, key): return {"id": "cached"}
    p = provider(lambda r: pytest.fail("No network call should occur"))
    assert p.request("responses", model="test", key="key", record=Cached(), json={})["id"] == "cached"


def test_frozen_job_models_override_later_environment_changes():
    p = LiveProvider(httpx.Client(base_url="https://test.invalid/v1/"),
                     config={"muse_model": "frozen-muse", "sam_model": "frozen-sam"})
    assert p.muse_model == "frozen-muse" and p.sam_model == "frozen-sam"


def test_semantic_schema_repair_is_separate_and_bounded(tmp_path):
    class Malformed:
        calls = 0
        def semantic(self, *args): self.calls += 1; return '{"not_a_plan": true}'
    p = Malformed()
    with pytest.raises(DomainError) as exc:
        parse_semantics(p, tmp_path / "clip.mp4", 12, Log())
    assert p.calls == 3 and exc.value.code == "E_SEMANTIC_SCHEMA"


def test_semantic_repair_can_recover(tmp_path):
    class Repaired:
        calls = 0
        def semantic(self, video, duration, prompt, schema, repair, record):
            self.calls += 1
            if self.calls == 1: return "invalid"
            assert repair["validation_error"]
            return fixture_plan(12).model_dump_json()
    p = Repaired()
    plan, raws = parse_semantics(p, tmp_path / "video.mp4", 12, Log())
    assert len(raws) == 2 and plan.actions


def test_whole_person_actor_requires_repair_before_sam_tracking(tmp_path):
    invalid = fixture_plan(12).model_dump(mode="json")
    invalid["entities"][0]["category"] = "person"
    invalid["entities"][0]["sam_prompt"] = "person"
    class Provider:
        calls = 0
        def semantic(self, video, duration, prompt, schema, repair, record):
            self.calls += 1
            if self.calls == 1:
                return json.dumps(invalid)
            assert "hand entities" in repair["validation_error"]
            return fixture_plan(12).model_dump_json()
    plan, outputs = parse_semantics(Provider(), tmp_path / "video.mp4", 12, Log())
    assert len(outputs) == 2
    assert plan.entities[0].sam_prompt == "human hand"


def test_release_warning_does_not_invent_grasp(tmp_path):
    data = fixture_plan(12).model_dump(mode="json")
    data["actions"] = [data["actions"][-1]]
    data["action_graph"] = {"nodes": ["a06"], "edges": []}
    class ExistingHold:
        def semantic(self, *args): return json.dumps(data)
    plan, _ = parse_semantics(ExistingHold(), tmp_path / "clip.mp4", 12, Log())
    assert len(plan.actions) == 1 and any("RELEASE without" in w for w in plan.warnings)


def test_sam_zero_matches_is_valid():
    assert sam_records("", 640, 360) == []


def test_sam_malformed_text_is_not_silently_accepted():
    with pytest.raises(DomainError): sam_records("<3f>bad output", 640, 360)


def test_sam_plain_text_is_not_treated_as_zero_matches():
    with pytest.raises(DomainError) as exc:
        sam_records("I cannot segment this video.", 640, 360)
    assert exc.value.code == "E_SAM_PARSE"


def test_sam_rejects_different_wire_frame_dimensions():
    payload = "~!!!!M!0c[0o91w?q1!pIH4pPRVp2B3'7`e.ioeAf6-k/#Xd8%dX9x("
    line = f"<0f>0<|box;x1=211;y1=228;x2=270;y2=254;w=640;h=668|><|mask;x=0;y=0;data=27,60,{payload}|>"
    with pytest.raises(DomainError) as exc:
        sam_records(line, 320, 334)
    assert exc.value.code == "E_SAM_COORDINATES"


def test_sam_mask_quota_is_checked_before_parser_decode(monkeypatch):
    monkeypatch.setattr("packages.meta_client.live.parse_sam_text", lambda _: pytest.fail("oversize mask decoded"))
    with pytest.raises(DomainError) as exc:
        sam_records("<0f>0<|mask;x=0;y=0;data=10001,10000,!bad|>", 320, 334)
    assert exc.value.code == "E_SAM_MASK"


def test_sam_visual_corrections_use_integer_pixels_and_merge_same_frame(tmp_path):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"synthetic transport fixture")
    requests = []
    def handle(request):
        if request.url.path.endswith("files"):
            return httpx.Response(200, json={"id": "file-test"})
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "completed", "output": []})
    p = provider(handle)
    corrections = [
        {"kind": "point", "frame_index": 3, "point": [12.75, 8.5]},
        {"kind": "box", "frame_index": 3, "bbox_xyxy": [10.1, 5.2, 20.2, 15.5]},
    ]
    assert p.track(source, "mug", 40, 20, corrections, Log()) == []
    payload = requests[0]
    text = payload["input"][0]["content"][0]["text"]
    assert text.count("<3f>") == 1
    assert "x=12;y=8;w=40;h=20" in text
    assert "x1=10;y1=5;x2=20;y2=15;w=40;h=20" in text
    assert payload["input"][0]["content"][1] == {"type": "input_video", "file_id": "file-test"}
    assert payload["metadata"] == {"mask_encoding": "one_bit", "include_confidence": "true"}


def test_official_sam_sample_is_box_local_and_frame_ids_are_explicit():
    # Public wire-format example, not a recorded project inference result.
    payload = "~!!!!M!0c[0o91w?q1!pIH4pPRVp2B3'7`e.ioeAf6-k/#Xd8%dX9x("
    line = f"<7f>2<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334|><|mask;x=0;y=0;data=27,60,{payload}|>"
    records = sam_records(line, 320, 334)
    assert len(records) == 1
    row = records[0]
    assert row["frame"] == 7 and row["object_id"] == "2"
    assert row["mask"].shape == (334, 320)
    assert not row["mask"][:228].any() and not row["mask"][:, :211].any()
    assert row["bbox"] == [211, 228, 271, 255]
    assert row["confidence"] is None


def test_sam_sparse_unordered_frames_and_confidence_are_preserved():
    payload = "~!!!!M!0c[0o91w?q1!pIH4pPRVp2B3'7`e.ioeAf6-k/#Xd8%dX9x("
    def line(frame, object_id):
        return f"<{frame}f>{object_id}<|box;x1=211;y1=228;x2=270;y2=254;w=320;h=334;c=0.75|><|mask;x=0;y=0;c=0.75;data=27,60,{payload}|>"
    records = sam_records("\n".join([line(7, 2), line(3, 0), line(3, 2)]), 320, 334)
    assert [(r["frame"], r["object_id"]) for r in records] == [(7, "2"), (3, "0"), (3, "2")]
    assert all(r["confidence"] == .75 for r in records)


def test_sam_one_bit_payload_preserves_pixels_and_half_open_bounds():
    # Synthetic 2x3 bitmap encoded by the pinned official codec, no model call.
    payload = "!!!!!'Mar)f!!"
    line = f"<0f>0<|box;x1=1;y1=1;x2=3;y2=2;w=5;h=4|><|mask;x=0;y=0;data=2,3,{payload}|>"
    record, = sam_records(line, 5, 4)
    expected = np.zeros((4, 5), dtype=np.uint8)
    expected[1:3, 1:4] = [[0, 1, 0], [1, 1, 1]]
    assert np.array_equal(record["mask"], expected)
    assert record["bbox"] == [1, 1, 4, 3]


def test_muse_file_reference_and_output_contract(tmp_path):
    source = tmp_path / "media.mp4"
    source.write_bytes(b"synthetic transport fixture")
    payloads = []
    def handle(request):
        if request.url.path.endswith("files"):
            assert b"user_data" in request.content
            return httpx.Response(200, json={"id": "file-test"})
        payloads.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "response-test", "status": "completed", "usage": {"input_tokens": 7},
            "output": [{"content": [{"type": "output_text", "text": fixture_plan(12).model_dump_json()}]}]})
    log = Log()
    output = provider(handle).semantic(source, 12, "prompt", {}, None, log)
    assert json.loads(output)["canonical_skill"] == "pour"
    assert payloads[0]["input"][0]["content"][1] == {"type": "input_file", "file_id": "file-test"}
    assert log.events[-1]["usage"]["input_tokens"] == 7
