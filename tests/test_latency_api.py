from datetime import timedelta

from backend.database import SessionLocal
from backend.models import LatencyHourly, LatencySample
from collector.latency import utcnow


def create_target(client, **overrides):
    payload = {"name": "Router", "host": "192.168.50.1", "layer": "lan", **overrides}
    return client.post("/api/latency/targets", json=payload)


def seed_samples(target_id, count=3, median=10.0, received=10):
    db = SessionLocal()
    now = utcnow()
    for i in range(count):
        db.add(
            LatencySample(
                target_id=target_id,
                timestamp=now - timedelta(minutes=count - 1 - i),
                sent=10,
                received=received,
                min_ms=median - 1,
                median_ms=median,
                avg_ms=median,
                max_ms=median + 1,
                jitter_ms=0.5,
                under_load=False,
            )
        )
    db.commit()
    db.close()


def test_target_crud(client):
    created = create_target(client)
    assert created.status_code == 201
    target_id = created.get_json()["id"]

    assert create_target(client).status_code == 409
    assert [t["name"] for t in client.get("/api/latency/targets").get_json()] == ["Router"]

    updated = client.put(f"/api/latency/targets/{target_id}", json={"enabled": False, "host": "router.lan"})
    assert updated.get_json()["enabled"] is False
    assert updated.get_json()["host"] == "router.lan"

    assert client.delete(f"/api/latency/targets/{target_id}").status_code == 200
    assert client.delete(f"/api/latency/targets/{target_id}").status_code == 404
    assert client.put(f"/api/latency/targets/{target_id}", json={"enabled": True}).status_code == 404


def test_target_validation(client):
    assert create_target(client, layer="mars").status_code == 400
    assert create_target(client, host="bad host; rm -rf").status_code == 400
    assert create_target(client, name="").status_code == 400
    assert client.post("/api/latency/targets", json={"name": "x"}).status_code == 400


def test_deleting_a_target_removes_its_samples(client):
    target_id = create_target(client).get_json()["id"]
    seed_samples(target_id)
    client.delete(f"/api/latency/targets/{target_id}")
    db = SessionLocal()
    assert db.query(LatencySample).count() == 0
    db.close()


def test_latency_returns_raw_columns_for_short_ranges(client):
    target_id = create_target(client).get_json()["id"]
    seed_samples(target_id, count=3, received=9)
    body = client.get(f"/api/latency?target={target_id}").get_json()
    assert body["resolution"] == "raw"
    [series] = body["targets"]
    assert len(series["t"]) == 3
    assert series["median"] == [10.0, 10.0, 10.0]
    assert series["loss_pct"] == [10.0, 10.0, 10.0]


def test_latency_switches_to_hourly_beyond_seven_days(client):
    target_id = create_target(client).get_json()["id"]
    db = SessionLocal()
    db.add(
        LatencyHourly(
            target_id=target_id, hour=utcnow() - timedelta(days=20), median_ms=5.0, p95_ms=7.0, loss_pct=1.0, samples=60
        )
    )
    db.commit()
    db.close()
    start = (utcnow() - timedelta(days=30)).isoformat() + "+00:00"
    body = client.get("/api/latency", query_string={"target": target_id, "from": start}).get_json()
    assert body["resolution"] == "hourly"
    assert body["targets"][0]["p95"] == [7.0]


def test_latency_rejects_bad_ranges(client):
    assert client.get("/api/latency?from=nonsense").status_code == 400
    assert client.get("/api/latency?from=2026-01-02T00:00:00&to=2026-01-01T00:00:00").status_code == 400


def test_summary_reports_state_and_diagnosis(client):
    router = create_target(client).get_json()["id"]
    google = create_target(client, name="Google", host="8.8.8.8", layer="internet").get_json()["id"]
    seed_samples(router)
    seed_samples(google, received=0)
    body = client.get("/api/latency/summary").get_json()
    states = {t["name"]: t["state"] for t in body["targets"]}
    assert states == {"Router": "ok", "Google": "down"}
    assert body["diagnosis"]["code"] == "destination"
    router_entry = next(t for t in body["targets"] if t["name"] == "Router")
    assert router_entry["median_ms"] == 10.0
    assert router_entry["loss_1h_pct"] == 0.0
    assert router_entry["p95_24h_ms"] == 10.0


def test_summary_omits_disabled_targets(client):
    create_target(client, enabled=False)
    assert client.get("/api/latency/summary").get_json()["targets"] == []


def test_settings_expose_latency_defaults_and_validate(client):
    assert client.get("/api/settings").get_json()["latency_loss_pct"] == 5.0
    assert client.post("/api/settings", json={"latency_loss_pct": 500}).status_code == 400
    assert client.post("/api/settings", json={"latency_loss_pct": 8}).status_code == 200
    assert client.get("/api/settings").get_json()["latency_loss_pct"] == "8"


def test_speedtests_include_loaded_latency(client):
    from backend.models import SpeedTestResult

    db = SessionLocal()
    db.add(SpeedTestResult(download=1, upload=1, ping=10, server_name="s", server_id="1", loaded_latency=55.0))
    db.commit()
    db.close()
    assert client.get("/api/speedtests").get_json()[0]["loaded_latency"] == 55.0


