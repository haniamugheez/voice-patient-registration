"""Vapi webhook — the bridge between the voice agent and the data layer.

Vapi POSTs every server-side event here. We care about two message types:

  * ``tool-calls``          — the assistant wants to run one of our functions
                              (look up a caller, register them, update them).
  * ``end-of-call-report``  — the call finished; store the transcript.

The tool-call contract Vapi expects back is:

    { "results": [ { "toolCallId": "<id>", "result": "<string the LLM reads>" } ] }

Design note: the ``result`` string is written to be *spoken*, not parsed. If we
hand the model raw validation errors it reads them out verbatim and sounds like
a compiler. Instead each failure is phrased as an instruction to the agent
("Tell the caller ... and ask again for their date of birth"), which is what
produces the field-specific re-prompt the spec asks for.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import crud
from app.config import settings
from app.database import get_db
from app.schemas import PatientCreate, PatientUpdate, normalize_phone

logger = logging.getLogger("vapi")

router = APIRouter(prefix="/vapi", tags=["vapi"])


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def verify_secret(x_vapi_secret: str | None = Header(default=None)) -> None:
    """Vapi sends the configured server secret on every request."""
    if not settings.VAPI_SERVER_SECRET:
        return  # dev mode: no secret configured
    if x_vapi_secret != settings.VAPI_SERVER_SECRET:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"type": "unauthorized", "message": "Invalid webhook secret"},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize the several shapes Vapi has used for tool calls."""
    calls: list[dict[str, Any]] = []
    raw = message.get("toolCallList") or message.get("toolCalls") or []
    for item in raw:
        fn = item.get("function") or {}
        name = item.get("name") or fn.get("name")
        args = item.get("arguments")
        if args is None:
            args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        calls.append({"id": item.get("id") or item.get("toolCallId"),
                      "name": name, "arguments": args or {}})

    # Legacy single-function shape
    if not calls and message.get("functionCall"):
        fc = message["functionCall"]
        args = fc.get("parameters") or fc.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        calls.append({"id": fc.get("id"), "name": fc.get("name"), "arguments": args})
    return calls


def _friendly_errors(exc: ValidationError) -> str:
    """Turn pydantic errors into one short instruction for the voice agent."""
    parts = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"]) or "field"
        msg = err["msg"].replace("Value error, ", "")
        parts.append(f"{field}: {msg}")
    fields = ", ".join(sorted({str(e["loc"][0]) for e in exc.errors() if e["loc"]}))
    return (
        "NOT SAVED. These fields are invalid — "
        + "; ".join(parts)
        + f". Apologise briefly and ask the caller again only for: {fields}. "
        "Do not call this tool again until you have corrected values."
    )


def _caller_number(message: dict[str, Any]) -> str | None:
    call = message.get("call") or {}
    customer = call.get("customer") or {}
    return customer.get("number") or message.get("customer", {}).get("number")


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------
def tool_lookup_patient(args: dict, db: Session, message: dict) -> str:
    """Duplicate detection: does a record already exist for this phone number?"""
    raw = args.get("phone_number") or _caller_number(message)
    try:
        phone = normalize_phone(raw)
    except ValueError:
        return (
            "Could not read that phone number. Ask the caller to say their "
            "10-digit phone number again, one digit at a time."
        )
    existing = crud.get_patient_by_phone(db, phone)
    if not existing:
        return (
            "NO_MATCH. No existing record for this number. Proceed with a new "
            "registration."
        )
    return (
        f"MATCH_FOUND. An existing record belongs to {existing.first_name} "
        f"{existing.last_name}, patient_id {existing.patient_id}, "
        f"date of birth {existing.date_of_birth.strftime('%m/%d/%Y')}. "
        "Greet them by first name, say you already have a record, and ask "
        "whether they want to update it instead of creating a new one. "
        "If they say yes, use update_patient with this patient_id."
    )


def tool_register_patient(args: dict, db: Session, message: dict) -> str:
    """Validate + persist a new patient record."""
    # If the caller never spelled out a phone number, fall back to caller ID.
    if not args.get("phone_number"):
        args["phone_number"] = _caller_number(message)

    try:
        payload = PatientCreate(**args)
    except ValidationError as exc:
        logger.warning("vapi.register.validation_failed args=%s", args)
        return _friendly_errors(exc)

    # Duplicate guard — never silently create a second record for one number.
    existing = crud.get_patient_by_phone(db, payload.phone_number)
    if existing:
        return (
            f"DUPLICATE. A record already exists for that phone number "
            f"({existing.first_name} {existing.last_name}, patient_id "
            f"{existing.patient_id}). Ask the caller whether to update that "
            "record instead; if yes, call update_patient with this patient_id."
        )

    try:
        patient = crud.create_patient(db, payload)
    except SQLAlchemyError:
        db.rollback()
        logger.exception("vapi.register.db_error")
        return (
            "SAVE_FAILED. The system could not save the record right now. "
            "Apologise to the caller, tell them our system is temporarily "
            "unavailable and that someone will call them back, then end the call "
            "politely. Do not retry more than once."
        )

    logger.info("vapi.register.success payload=%s", payload.model_dump(mode="json"))
    return (
        f"SAVED. Patient {patient.first_name} {patient.last_name} registered "
        f"successfully with patient_id {patient.patient_id}. Confirm to the "
        f"caller that they are all set and end the call warmly."
    )


def tool_update_patient(args: dict, db: Session, message: dict) -> str:
    patient_id = args.pop("patient_id", None)
    patient = crud.get_patient(db, patient_id) if patient_id else None

    # Fall back to the caller's number if the model lost the id.
    if not patient:
        raw = args.get("phone_number") or _caller_number(message)
        try:
            patient = crud.get_patient_by_phone(db, normalize_phone(raw))
        except (ValueError, TypeError):
            patient = None
    if not patient:
        return (
            "NOT_FOUND. No existing record to update. Tell the caller you will "
            "create a new registration instead, then collect their details and "
            "call register_patient."
        )

    try:
        payload = PatientUpdate(**args)
    except ValidationError as exc:
        return _friendly_errors(exc)

    if not payload.model_dump(exclude_unset=True, exclude_none=True):
        return "NO_CHANGES. Ask the caller which specific details they want to change."

    try:
        patient = crud.update_patient(db, patient, payload)
    except SQLAlchemyError:
        db.rollback()
        logger.exception("vapi.update.db_error")
        return (
            "SAVE_FAILED. Could not update the record. Apologise, say someone "
            "will follow up, and end the call politely."
        )

    return (
        f"UPDATED. Record for {patient.first_name} {patient.last_name} "
        f"(patient_id {patient.patient_id}) updated successfully. Confirm to the "
        "caller and end the call warmly."
    )


TOOLS = {
    "lookup_patient": tool_lookup_patient,
    "register_patient": tool_register_patient,
    "update_patient": tool_update_patient,
}


# ---------------------------------------------------------------------------
# Webhook entry point
# ---------------------------------------------------------------------------
@router.post("/webhook", dependencies=[Depends(verify_secret)])
async def vapi_webhook(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    message = body.get("message", body) or {}
    msg_type = message.get("type")

    logger.info("vapi.webhook type=%s", msg_type)

    # ---- 1. Tool calls ----------------------------------------------------
    if msg_type in {"tool-calls", "function-call"}:
        results = []
        for call in _parse_tool_calls(message):
            handler = TOOLS.get(call["name"])
            if not handler:
                result = f"Unknown tool '{call['name']}'."
            else:
                logger.info("vapi.tool name=%s args=%s", call["name"], call["arguments"])
                try:
                    result = handler(dict(call["arguments"]), db, message)
                except Exception:  # never 500 back at a live phone call
                    logger.exception("vapi.tool.unhandled name=%s", call["name"])
                    result = (
                        "SYSTEM_ERROR. Something went wrong on our side. "
                        "Apologise to the caller and offer to try once more."
                    )
            results.append({"toolCallId": call["id"], "result": result})
        return {"results": results}

    # ---- 2. End-of-call report (bonus: transcript storage) ----------------
    if msg_type == "end-of-call-report":
        call = message.get("call") or {}
        caller = _caller_number(message)
        patient = None
        if caller:
            try:
                patient = crud.get_patient_by_phone(db, normalize_phone(caller))
            except ValueError:
                patient = None
        transcript = message.get("transcript")
        if not transcript and message.get("artifact"):
            transcript = message["artifact"].get("transcript")
        crud.save_transcript(
            db,
            call_id=call.get("id"),
            caller_number=caller,
            patient_id=patient.patient_id if patient else None,
            summary=message.get("summary"),
            transcript=transcript,
            ended_reason=message.get("endedReason"),
        )
        logger.info("vapi.call_ended reason=%s", message.get("endedReason"))
        return {"received": True}

    # ---- 3. Everything else (status-update, speech-update, ...) -----------
    return {"received": True}
