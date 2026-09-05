"""Integration tests for the REST API and the Vapi webhook.

Each test runs against a throwaway SQLite file, so the suite never touches the
real database. Run with:  pytest -q
"""

import os
import tempfile
from datetime import date, timedelta

import pytest

os.environ["DATABASE_URL"] = (
    "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db")
)
os.environ["SEED_ON_STARTUP"] = "false"
# Empty (not absent): load_dotenv() does not override keys already present,
# so this keeps a developer's local .env from leaking into the test run.
os.environ["VAPI_SERVER_SECRET"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


VALID = {
    "first_name": "Ada",
    "last_name": "Lovelace",
    "date_of_birth": "12/10/1985",
    "sex": "female",
    "phone_number": "(415) 555-0132",
    "address_line_1": "1 Analytical Way",
    "city": "San Francisco",
    "state": "California",
    "zip_code": "94107",
}


def _new(**overrides):
    payload = dict(VALID)
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Health & envelope
# ---------------------------------------------------------------------------
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["error"] is None


# ---------------------------------------------------------------------------
# Create + normalization
# ---------------------------------------------------------------------------
def test_create_normalizes_input(client):
    r = client.post("/patients", json=_new(date_of_birth="04/12/1985"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["error"] is None
    data = body["data"]
    # phone stripped to 10 digits, state mapped to abbreviation, sex title-cased
    assert data["phone_number"] == "4155550132"
    assert data["state"] == "CA"
    assert data["sex"] == "Female"
    assert data["date_of_birth"] == "1985-04-12"
    assert len(data["patient_id"]) == 36
    assert data["deleted_at"] is None


def test_rejects_short_phone(client):
    r = client.post("/patients", json=_new(phone_number="415555", last_name="Short"))
    assert r.status_code == 422
    assert r.json()["error"]["type"] == "validation_error"
    fields = [d["field"] for d in r.json()["error"]["details"]]
    assert "phone_number" in fields


def test_rejects_future_dob(client):
    future = (date.today() + timedelta(days=30)).strftime("%m/%d/%Y")
    r = client.post("/patients", json=_new(date_of_birth=future, phone_number="4155550199"))
    assert r.status_code == 422
    assert any("future" in d["message"] for d in r.json()["error"]["details"])


def test_rejects_bad_state_and_zip(client):
    r = client.post("/patients", json=_new(state="Freedonia", phone_number="4155550177"))
    assert r.status_code == 422
    r = client.post("/patients", json=_new(zip_code="9410", phone_number="4155550178"))
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Read / query
# ---------------------------------------------------------------------------
def test_get_and_query(client):
    created = client.post(
        "/patients", json=_new(last_name="Turing", phone_number="6505550111")
    ).json()["data"]

    r = client.get(f"/patients/{created['patient_id']}")
    assert r.status_code == 200
    assert r.json()["data"]["last_name"] == "Turing"

    assert client.get("/patients?last_name=turing").json()["data"][0][
        "patient_id"
    ] == created["patient_id"]
    assert len(client.get("/patients?phone_number=650-555-0111").json()["data"]) == 1
    assert client.get("/patients?date_of_birth=12/10/1985").json()["data"]


def test_get_unknown_id_is_404(client):
    r = client.get("/patients/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
    assert r.json()["error"]["type"] == "not_found"


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------
def test_partial_update(client):
    pid = client.post(
        "/patients", json=_new(phone_number="3105550101", last_name="Hopper")
    ).json()["data"]["patient_id"]

    r = client.put(f"/patients/{pid}", json={"city": "Arlington", "state": "VA"})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["city"] == "Arlington" and data["state"] == "VA"
    assert data["last_name"] == "Hopper"  # untouched


def test_update_validates(client):
    pid = client.post(
        "/patients", json=_new(phone_number="3105550102", last_name="Noether")
    ).json()["data"]["patient_id"]
    r = client.put(f"/patients/{pid}", json={"zip_code": "abcde"})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Soft delete
# ---------------------------------------------------------------------------
def test_soft_delete_hides_but_keeps(client):
    pid = client.post(
        "/patients", json=_new(phone_number="2065550100", last_name="Curie")
    ).json()["data"]["patient_id"]

    assert client.delete(f"/patients/{pid}").status_code == 200
    assert client.get(f"/patients/{pid}").status_code == 404
    # still present when explicitly asked for
    ids = [p["patient_id"] for p in
           client.get("/patients?include_deleted=true").json()["data"]]
    assert pid in ids


# ---------------------------------------------------------------------------
# Vapi webhook
# ---------------------------------------------------------------------------
def _tool_call(name, args, caller="+14805550100"):
    return {
        "message": {
            "type": "tool-calls",
            "call": {"id": "call_test_1", "customer": {"number": caller}},
            "toolCallList": [{"id": "tc_1", "name": name, "arguments": args}],
        }
    }


def test_webhook_registers_patient(client):
    r = client.post(
        "/vapi/webhook",
        json=_tool_call("register_patient", _new(phone_number="4805550100",
                                                last_name="Franklin")),
    )
    assert r.status_code == 200
    result = r.json()["results"][0]["result"]
    assert result.startswith("SAVED")
    assert client.get("/patients?phone_number=4805550100").json()["data"]


def test_webhook_lookup_finds_returning_caller(client):
    r = client.post("/vapi/webhook", json=_tool_call("lookup_patient", {}))
    result = r.json()["results"][0]["result"]
    assert "MATCH_FOUND" in result and "Franklin" in result


def test_webhook_lookup_no_match(client):
    r = client.post(
        "/vapi/webhook",
        json=_tool_call("lookup_patient", {"phone_number": "9995550123"}),
    )
    assert "NO_MATCH" in r.json()["results"][0]["result"]


def test_webhook_invalid_field_returns_reprompt_instruction(client):
    r = client.post(
        "/vapi/webhook",
        json=_tool_call(
            "register_patient",
            _new(date_of_birth="13/45/2099", phone_number="4805550111"),
            caller="+14805550111",
        ),
    )
    result = r.json()["results"][0]["result"]
    assert "NOT SAVED" in result
    assert "date_of_birth" in result


def test_webhook_detects_duplicate(client):
    r = client.post(
        "/vapi/webhook",
        json=_tool_call("register_patient", _new(phone_number="4805550100",
                                                last_name="Franklin")),
    )
    assert "DUPLICATE" in r.json()["results"][0]["result"]


def test_webhook_updates_existing(client):
    pid = client.get("/patients?phone_number=4805550100").json()["data"][0]["patient_id"]
    r = client.post(
        "/vapi/webhook",
        json=_tool_call("update_patient", {"patient_id": pid, "city": "Boston",
                                           "state": "MA"}),
    )
    assert "UPDATED" in r.json()["results"][0]["result"]
    assert client.get(f"/patients/{pid}").json()["data"]["city"] == "Boston"


def test_webhook_stores_transcript(client):
    r = client.post(
        "/vapi/webhook",
        json={
            "message": {
                "type": "end-of-call-report",
                "call": {"id": "call_test_1", "customer": {"number": "+14805550100"}},
                "endedReason": "customer-ended-call",
                "summary": "Caller updated their address.",
                "transcript": "AI: Hello ... User: ...",
            }
        },
    )
    assert r.status_code == 200
    assert client.get("/dashboard").status_code == 200


def test_webhook_ignores_unknown_message_types(client):
    r = client.post("/vapi/webhook", json={"message": {"type": "speech-update"}})
    assert r.status_code == 200


def test_webhook_rejects_wrong_secret_when_configured(client, monkeypatch):
    """With a secret configured, the webhook must reject unsigned requests."""
    monkeypatch.setattr(settings, "VAPI_SERVER_SECRET", "s3cr3t")
    payload = {"message": {"type": "speech-update"}}

    assert client.post("/vapi/webhook", json=payload).status_code == 401
    assert client.post(
        "/vapi/webhook", json=payload, headers={"x-vapi-secret": "wrong"}
    ).status_code == 401
    assert client.post(
        "/vapi/webhook", json=payload, headers={"x-vapi-secret": "s3cr3t"}
    ).status_code == 200
