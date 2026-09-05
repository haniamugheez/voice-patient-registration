"""Simulate the voice agent's tool calls without a phone.

Useful for testing the whole data path before (or instead of) provisioning a
number. It sends exactly the payloads Vapi sends.

    python scripts/simulate_call.py                       # against localhost
    python scripts/simulate_call.py https://your.onrender.com
"""

import json
import sys

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
SECRET = None  # set to your VAPI_SERVER_SECRET if the server enforces one

CALLER = "+14155559911"

NEW_PATIENT = {
    "first_name": "Marcus",
    "last_name": "Chen",
    "date_of_birth": "07/22/1990",
    "sex": "Male",
    "phone_number": "4155559911",
    "address_line_1": "88 Market Street",
    "address_line_2": "Suite 300",
    "city": "San Francisco",
    "state": "CA",
    "zip_code": "94105",
    "email": "marcus.chen@example.com",
    "insurance_provider": "Aetna",
    "insurance_member_id": "AET77321",
    "emergency_contact_name": "Lily Chen",
    "emergency_contact_phone": "4155559922",
}


def tool_call(name: str, arguments: dict) -> dict:
    return {
        "message": {
            "type": "tool-calls",
            "call": {"id": "sim_call_1", "customer": {"number": CALLER}},
            "toolCallList": [{"id": "tc_sim", "name": name, "arguments": arguments}],
        }
    }


def send(payload: dict) -> dict:
    headers = {"x-vapi-secret": SECRET} if SECRET else {}
    r = httpx.post(f"{BASE}/vapi/webhook", json=payload, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def show(label: str, response: dict) -> None:
    print(f"\n=== {label} ===")
    results = response.get("results")
    if results:
        print(results[0]["result"])
    else:
        print(json.dumps(response))


if __name__ == "__main__":
    print(f"Simulating a call against {BASE}")

    show("1. Agent checks for an existing record",
         send(tool_call("lookup_patient", {})))

    show("2. Caller gives a bad date of birth",
         send(tool_call("register_patient", {**NEW_PATIENT,
                                             "date_of_birth": "02/30/2035"})))

    show("3. Caller corrects it; agent saves",
         send(tool_call("register_patient", NEW_PATIENT)))

    show("4. Same caller phones back — duplicate detection",
         send(tool_call("lookup_patient", {})))

    show("5. End-of-call transcript stored",
         send({
             "message": {
                 "type": "end-of-call-report",
                 "call": {"id": "sim_call_1", "customer": {"number": CALLER}},
                 "endedReason": "customer-ended-call",
                 "summary": "Marcus Chen registered as a new patient.",
                 "transcript": "AI: Thanks for calling... User: Hi, I'd like to register.",
             }
         }))

    print(f"\nNow open {BASE}/dashboard to see the record.")
