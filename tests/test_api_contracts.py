from fastapi.testclient import TestClient

from apps.api.main import app


def test_invalid_upload_returns_machine_readable_error():
    with TestClient(app) as client:
        response = client.post("/v1/videos", json={"filename": "test"})
    assert response.status_code == 422
    assert response.json()["code"] == "E_REQUEST_SCHEMA"
    assert "input" not in response.json()


def test_openapi_exposes_real_response_contracts():
    with TestClient(app) as client:
        spec = client.get("/openapi.json").json()
    response = spec["paths"]["/v1/videos/{video_id}/tracks"]["get"]["responses"]["200"]
    assert response["content"]["application/json"]["schema"]["$ref"].endswith("TracksResponse")
