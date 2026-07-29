def test_health_endpoint_under_svc_api(client):
    resp = client.get("/svc/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
