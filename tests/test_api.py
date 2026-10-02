"""
REST API tests (FastAPI TestClient) and the docs-in-sync check.
"""
import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    os.environ["AUDIT_LEDGER_PATH"] = str(tmp_path_factory.mktemp("ledger") / "ledger.jsonl")
    os.environ["AUDIT_HMAC_KEY"] = "test-key"
    import server
    return TestClient(server.app)


PII_REQUEST = {
    "request_id": "API-PII-1", "user_name": 'ד"ר אלון לוי', "user_role": "data_scientist", "department": "Research",
    "tool_name": "Enterprise-Clinical-Predictor", "deployment_type": "DEDICATED_CLOUD",
    "data_sensitivity": "RESTRICTED_PII", "has_signed_dpa": True, "intended_use": "Statistical analysis of anonymized records",
    "tos_text": "Hosted in Germany (EU). No model training on customer data. Data retained for 30 days. Encryption at rest (AES-256).",
}


def test_state_machine_endpoint(client):
    body = client.get("/api/state-machine").json()
    assert len(body["states"]) == 18 and len(body["transitions"]) == 31 and len(body["ltl"]) == 6


def test_hitl_flow_over_http(client):
    d = client.post("/api/evaluate", json=PII_REQUEST).json()
    assert d["status"] == "HUMAN_REVIEW"
    assert any(p["request_id"] == "API-PII-1" for p in client.get("/api/pending").json())

    r = client.post("/api/requests/API-PII-1/officer-decision", json={"officer_name": 'ד"ר אלון לוי', "action": "APPROVE"})
    assert r.status_code == 403

    r = client.post("/api/requests/API-PII-1/officer-decision", json={"officer_name": "רונית כהן", "action": "APPROVE"})
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"

    r = client.post("/api/requests/API-PII-1/officer-decision", json={"officer_name": "רונית כהן", "action": "APPROVE"})
    assert r.status_code == 409  # no longer awaiting review


def test_duplicate_and_unknown_ids(client):
    assert client.post("/api/evaluate", json=PII_REQUEST).status_code == 409
    assert client.get("/api/requests/NOPE").status_code == 404


def test_bypass_demo_endpoint(client):
    attempts = client.post("/api/demo/bypass-attempt").json()["attempts"]
    assert len(attempts) == 2


def test_audit_trail_endpoint_and_token(client, monkeypatch):
    body = client.get("/api/audit-trail").json()
    assert body["integrity_verified"] and body["total_records"] >= 1
    monkeypatch.setenv("API_TOKEN", "secret")
    assert client.get("/api/audit-trail").status_code == 401
    assert client.get("/api/audit-trail", headers={"X-API-Token": "secret"}).status_code == 200


def test_transitions_doc_is_generated_from_code():
    from scripts.generate_transitions_doc import render
    path = os.path.join(os.path.dirname(__file__), "..", "docs", "TRANSITIONS_TABLE.md")
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == render(), "docs/TRANSITIONS_TABLE.md is stale: run python3 scripts/generate_transitions_doc.py"
