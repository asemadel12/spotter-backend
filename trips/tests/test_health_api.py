from rest_framework.test import APIClient


def test_health_endpoint_returns_ok():
    response = APIClient().get("/api/health/")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
