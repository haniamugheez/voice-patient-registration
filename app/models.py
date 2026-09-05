"""Database models.

One table for patients (the demographic dataset from the spec) and one table
for call transcripts, so each registration can be traced back to the phone call
that produced it.
"""

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid4() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Patient(Base):
    __tablename__ = "patients"

    # --- identity ----------------------------------------------------------
    patient_id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=_uuid4
    )

    # --- required demographics --------------------------------------------
    first_name: Mapped[str] = mapped_column(String(50), nullable=False)
    last_name: Mapped[str] = mapped_column(String(50), nullable=False)
    date_of_birth: Mapped[date] = mapped_column(Date, nullable=False)
    sex: Mapped[str] = mapped_column(String(20), nullable=False)
    # Stored normalized as 10 digits so lookups by phone are exact matches.
    phone_number: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    address_line_1: Mapped[str] = mapped_column(String(200), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(2), nullable=False)
    zip_code: Mapped[str] = mapped_column(String(10), nullable=False)

    # --- optional demographics --------------------------------------------
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    address_line_2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    insurance_provider: Mapped[str | None] = mapped_column(String(120), nullable=True)
    insurance_member_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    preferred_language: Mapped[str | None] = mapped_column(
        String(50), nullable=True, default="English"
    )
    emergency_contact_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # --- audit -------------------------------------------------------------
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )
    # Soft delete: rows are never removed, only stamped.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    transcripts: Mapped[list["CallTranscript"]] = relationship(
        back_populates="patient", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_patients_last_name", "last_name"),
        Index("ix_patients_dob", "date_of_birth"),
    )


class CallTranscript(Base):
    """Bonus: a record of each voice call, linked to the patient when known."""

    __tablename__ = "call_transcripts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid4)
    call_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    caller_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    patient_id: Mapped[str | None] = mapped_column(
        ForeignKey("patients.patient_id"), nullable=True
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    ended_reason: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    patient: Mapped[Patient | None] = relationship(back_populates="transcripts")
