import pytest

from perisentra.config import PATHS

pytestmark = pytest.mark.skipif(not (PATHS.serving / "recommendations.parquet").exists(), reason="no scoring run yet")


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from perisentra.api.main import app

    return TestClient(app)


def test_health_and_meta(client):
    assert client.get("/api/health").json()["status"] == "ok"
    meta = client.get("/api/meta").json()
    assert meta["stores"] and meta["families"]


def test_overview_kpis_are_consistent(client):
    k = client.get("/api/overview").json()["kpi"]
    assert k["expected_waste"] <= k["stock_at_risk"] + 1e-6
    assert k["markdowns"] >= 0 and k["items"] > 0


def test_recommendation_detail_has_candidates_and_reasons(client):
    items = client.get("/api/recommendations", params={"action": "MARKDOWN", "limit": 1}).json()["items"]
    if not items:
        pytest.skip("no markdowns today")
    r = items[0]
    d = client.get(f"/api/recommendations/{r['store_id']}/{r['sku_id']}").json()
    assert d["candidates"] and any(c["chosen"] for c in d["candidates"])
    assert d["recommendation"]["reason_codes"]
    assert len(d["forecast"]) == 7


def test_rules_validation_endpoint(client):
    bad = client.post("/api/rules/validate", json={"rules": {"markdown": {"ladder_pct": [150]}}}).json()
    assert bad["valid"] is False and bad["errors"]
