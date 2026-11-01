import json
import sys

import httpx

from scripts import live_smoke


def test_real_video_preflight_never_submits_fixture_inference(tmp_path, monkeypatch):
    source = tmp_path / "real.mp4"
    source.write_bytes(b"transport fixture only; server media validation mocked")
    report = tmp_path / "report.json"
    calls = []
    def handler(request):
        calls.append((request.method, request.url.path))
        assert not request.url.path.endswith("/process"), "A fixture inference job must never be submitted"
        if request.url.path == "/health/ready":
            return httpx.Response(200, json={"inference_mode": "fixture"})
        if request.url.path == "/v1/videos":
            payload = json.loads(request.content)
            assert payload["provenance"]["source_uri"] == "https://example.test/source"
            return httpx.Response(201, json={"video_id": "real-video", "upload_url": "https://store.test/object", "upload_headers": {}})
        if request.method == "PUT":
            return httpx.Response(200)
        return httpx.Response(200, json={"status": "UPLOADED"})
    client = httpx.Client(base_url="http://localhost:58000", transport=httpx.MockTransport(handler))
    monkeypatch.setattr(live_smoke.httpx, "Client", lambda **_: client)
    class Config:
        model_api_key = ""
    monkeypatch.setattr(live_smoke, "settings", Config)
    monkeypatch.setattr(sys, "argv", ["live_smoke", "--source", str(source), "--report", str(report),
        "--source-uri", "https://example.test/source", "--rights", "user_supplied"])
    live_smoke.main()
    result = json.loads(report.read_text())
    assert result["status"] == "blocked" and result["real_model_calls"] == 0
    assert not result["live_inference_submitted"]
    assert result["upload_status"] == "UPLOADED"
