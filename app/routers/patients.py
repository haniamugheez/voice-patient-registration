"""REST API for patient records.

Every response uses the envelope { "data": ..., "error": ... } required by the
spec. Errors are raised as HTTPException with a structured detail payload and
converted to that envelope by the handlers in app/main.py.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db
from app.schemas import (
    PatientCreate,
    PatientOut,
    PatientUpdate,
    normalize_dob,
    normalize_phone,
)

router = APIRouter(prefix="/patients", tags=["patients"])


def _ok(data):
    return {"data": data, "error": None}


@router.get("", summary="List patients")
@router.get("/", include_in_schema=False)
def list_patients(
    db: Session = Depends(get_db),
    last_name: str | None = Query(None),
    date_of_birth: str | None = Query(None, description="MM/DD/YYYY or YYYY-MM-DD"),
    phone_number: str | None = Query(None),
    include_deleted: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    dob: date | None = None
    if date_of_birth:
        try:
            dob = normalize_dob(date_of_birth)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"type": "validation_error", "message": str(exc),
                        "field": "date_of_birth"},
            ) from exc
    phone: str | None = None
    if phone_number:
        try:
            phone = normalize_phone(phone_number)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"type": "validation_error", "message": str(exc),
                        "field": "phone_number"},
            ) from exc

    patients = crud.list_patients(
        db,
        last_name=last_name,
        date_of_birth=dob,
        phone_number=phone,
        include_deleted=include_deleted,
        limit=limit,
        offset=offset,
    )
    return _ok([PatientOut.model_validate(p).model_dump(mode="json") for p in patients])


@router.get("/{patient_id}", summary="Get one patient by UUID")
def get_patient(patient_id: str, db: Session = Depends(get_db)):
    patient = crud.get_patient(db, patient_id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"type": "not_found",
                    "message": f"No patient found with id {patient_id}"},
        )
    return _ok(PatientOut.model_validate(patient).model_dump(mode="json"))


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a patient")
@router.post("/", status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_patient(payload: PatientCreate, db: Session = Depends(get_db)):
    patient = crud.create_patient(db, payload)
    return _ok(PatientOut.model_validate(patient).model_dump(mode="json"))


@router.put("/{patient_id}", summary="Update a patient (partial updates allowed)")
def update_patient(
    patient_id: str, payload: PatientUpdate, db: Session = Depends(get_db)
):
    patient = crud.get_patient(db, patient_id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"type": "not_found",
                    "message": f"No patient found with id {patient_id}"},
        )
    if not payload.model_dump(exclude_unset=True, exclude_none=True):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"type": "bad_request", "message": "No updatable fields provided"},
        )
    patient = crud.update_patient(db, patient, payload)
    return _ok(PatientOut.model_validate(patient).model_dump(mode="json"))


@router.delete("/{patient_id}", summary="Soft-delete a patient")
def delete_patient(patient_id: str, response: Response, db: Session = Depends(get_db)):
    patient = crud.get_patient(db, patient_id)
    if not patient:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"type": "not_found",
                    "message": f"No patient found with id {patient_id}"},
        )
    patient = crud.soft_delete_patient(db, patient)
    return _ok(
        {
            "patient_id": patient.patient_id,
            "deleted_at": patient.deleted_at.isoformat() if patient.deleted_at else None,
        }
    )
