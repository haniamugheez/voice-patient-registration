"""Service layer.

Both the REST API and the voice-agent webhook call these functions, so the two
entry points can never drift apart in behaviour or validation.
"""

import logging
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CallTranscript, Patient
from app.schemas import PatientCreate, PatientUpdate

logger = logging.getLogger(__name__)


def list_patients(
    db: Session,
    last_name: str | None = None,
    date_of_birth: date | None = None,
    phone_number: str | None = None,
    include_deleted: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[Patient]:
    stmt = select(Patient)
    if not include_deleted:
        stmt = stmt.where(Patient.deleted_at.is_(None))
    if last_name:
        # Case-insensitive match: callers spell names, transcripts vary in case.
        stmt = stmt.where(Patient.last_name.ilike(last_name))
    if date_of_birth:
        stmt = stmt.where(Patient.date_of_birth == date_of_birth)
    if phone_number:
        stmt = stmt.where(Patient.phone_number == phone_number)
    stmt = stmt.order_by(Patient.created_at.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())


def get_patient(db: Session, patient_id: str, include_deleted: bool = False) -> Patient | None:
    stmt = select(Patient).where(Patient.patient_id == patient_id)
    if not include_deleted:
        stmt = stmt.where(Patient.deleted_at.is_(None))
    return db.execute(stmt).scalar_one_or_none()


def get_patient_by_phone(db: Session, phone_number: str) -> Patient | None:
    """Used for duplicate detection on inbound calls."""
    stmt = (
        select(Patient)
        .where(Patient.phone_number == phone_number, Patient.deleted_at.is_(None))
        .order_by(Patient.created_at.desc())
    )
    return db.execute(stmt).scalars().first()


def create_patient(db: Session, payload: PatientCreate) -> Patient:
    patient = Patient(**payload.model_dump())
    db.add(patient)
    db.commit()
    db.refresh(patient)
    logger.info(
        "patient.created id=%s name=%s %s phone=%s",
        patient.patient_id, patient.first_name, patient.last_name, patient.phone_number,
    )
    return patient


def update_patient(db: Session, patient: Patient, payload: PatientUpdate) -> Patient:
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in changes.items():
        setattr(patient, key, value)
    patient.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(patient)
    logger.info("patient.updated id=%s fields=%s", patient.patient_id, list(changes))
    return patient


def soft_delete_patient(db: Session, patient: Patient) -> Patient:
    """Never hard-delete: healthcare records need an audit trail."""
    patient.deleted_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(patient)
    logger.info("patient.soft_deleted id=%s", patient.patient_id)
    return patient


def save_transcript(
    db: Session,
    call_id: str | None,
    caller_number: str | None,
    patient_id: str | None,
    summary: str | None,
    transcript: str | None,
    ended_reason: str | None,
) -> CallTranscript:
    record = CallTranscript(
        call_id=call_id,
        caller_number=caller_number,
        patient_id=patient_id,
        summary=summary,
        transcript=transcript,
        ended_reason=ended_reason,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    logger.info("call.transcript_saved call_id=%s patient_id=%s", call_id, patient_id)
    return record
