"""Seed two demo patients so the API and dashboard are never empty on review.

Idempotent: if a record with the same phone number already exists, nothing
happens, so restarts never duplicate data.
"""

import logging

from app import crud
from app.database import SessionLocal
from app.schemas import PatientCreate

logger = logging.getLogger(__name__)

SEED_PATIENTS = [
    {
        "first_name": "Jane",
        "last_name": "Doe",
        "date_of_birth": "04/12/1985",
        "sex": "Female",
        "phone_number": "4155550132",
        "email": "jane.doe@example.com",
        "address_line_1": "742 Evergreen Terrace",
        "address_line_2": "Apt 4B",
        "city": "San Francisco",
        "state": "CA",
        "zip_code": "94107",
        "insurance_provider": "Blue Cross Blue Shield",
        "insurance_member_id": "BCBS884213",
        "preferred_language": "English",
        "emergency_contact_name": "John Doe",
        "emergency_contact_phone": "4155550188",
    },
    {
        "first_name": "Miguel",
        "last_name": "Ramirez",
        "date_of_birth": "11/03/1972",
        "sex": "Male",
        "phone_number": "2125550147",
        "address_line_1": "1200 Broadway",
        "city": "New York",
        "state": "NY",
        "zip_code": "10001",
        "preferred_language": "Spanish",
    },
]


def seed() -> None:
    db = SessionLocal()
    try:
        created = 0
        for row in SEED_PATIENTS:
            payload = PatientCreate(**row)
            if crud.get_patient_by_phone(db, payload.phone_number):
                continue
            crud.create_patient(db, payload)
            created += 1
        if created:
            logger.info("seed.inserted count=%d", created)
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from app.database import init_db

    init_db()
    seed()
