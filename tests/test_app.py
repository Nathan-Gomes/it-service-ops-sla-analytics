import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(built):
    from serviceops.app import app

    return TestClient(app)


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["tickets"] == 49_480


def test_index_has_security_headers(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_meta(client):
    meta = client.get("/api/meta").json()
    assert len(meta["categories"]) == 8 and meta["sla_goal_pct"] == 90


def test_overview_filters(client):
    all_ = client.get("/api/overview").json()["kpis"]["total_tickets"]
    some = client.get("/api/overview", params={"priority": ["Critical", "High"],
                                               "site": "Remote"}).json()
    assert 0 < some["kpis"]["total_tickets"] < all_
    assert {p["priority"] for p in some["priority"]} == {"Critical", "High"}


def test_breaches(client):
    body = client.get("/api/breaches").json()
    assert body["top_categories"] == ["Access & Identity", "Network & VPN"]
    assert body["matrix"] and body["drivers"] and body["subcategories"]
    single = client.get("/api/breaches", params={"category": "Printing"}).json()
    assert "top_categories" not in single


def test_quality(client):
    body = client.get("/api/quality").json()
    assert body["rows_quarantined"] == len(body["quarantine"]) == 520
    assert body["quarantine"][0]["raw_record"]["ticket_id"]


def test_tickets_paging_sorting_and_search(client):
    page = client.get("/api/tickets", params={"limit": 10, "sort": "elapsed_hours"}).json()
    hours = [r["elapsed_hours"] for r in page["rows"]]
    assert hours == sorted(hours, reverse=True) and page["total"] == 49_480
    hit = client.get("/api/tickets", params={"search": "INC1000001"}).json()
    assert hit["total"] == 1
    breached = client.get("/api/tickets", params={"state": "Breached", "limit": 5}).json()
    assert all(r["sla_state"] == "Breached" for r in breached["rows"])


def test_exports(client):
    csv = client.get("/api/tickets.csv", params={"category": "Printing", "priority": "Critical"})
    assert csv.status_code == 200 and csv.text.startswith("ticket_id,")
    xlsx = client.get("/api/report.xlsx")
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"


def test_cached_responses_are_keyed_by_filters(client):
    from serviceops.app import cache

    a = client.get("/api/overview", params={"category": "Printing"}).json()
    b = client.get("/api/overview", params={"category": "Security"}).json()
    again = client.get("/api/overview", params={"category": "Printing"}).json()
    assert a == again and a != b
    assert "/api/overview?category=Printing" in cache.items
