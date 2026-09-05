"""Pydantic schemas = the server-side validation layer.

Everything that enters the system — whether from the REST API or from a voice
agent tool call — is validated here. The voice agent is treated as an untrusted
client: its prompt asks it to validate, but the server never relies on that.
"""

import re
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# The 50 states + DC and the inhabited territories a U.S. provider would accept.
US_STATES: set[str] = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC", "PR", "VI", "GU", "AS", "MP",
}

# Full state names -> abbreviation. A caller says "California", not "C-A".
STATE_NAMES: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC", "puerto rico": "PR",
}

SEX_VALUES = ["Male", "Female", "Other", "Decline to Answer"]
SEX_ALIASES = {
    "m": "Male", "male": "Male", "man": "Male", "boy": "Male",
    "f": "Female", "female": "Female", "woman": "Female", "girl": "Female",
    "o": "Other", "other": "Other", "non-binary": "Other", "nonbinary": "Other",
    "x": "Other",
    "decline": "Decline to Answer", "decline to answer": "Decline to Answer",
    "prefer not to say": "Decline to Answer", "unknown": "Decline to Answer",
    "n/a": "Decline to Answer",
}

NAME_RE = re.compile(r"^[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\-'’. ]{0,49}$")
ZIP_RE = re.compile(r"^\d{5}(-\d{4})?$")


# ----------------------------------------------------------------------------
# Normalizers — shared by the API and the voice-agent webhook
# ----------------------------------------------------------------------------
def normalize_phone(value: Any) -> str:
    """Reduce anything phone-shaped to 10 digits, or raise ValueError.

    A speech-to-text engine yields things like "(415) 555-0132", "+1 415 555
    0132" or "four one five...". We strip everything but digits, drop a leading
    US country code, and then insist on exactly 10 digits.
    """
    if value is None:
        raise ValueError("phone number is required")
    digits = re.sub(r"\D", "", str(value))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError("phone number must be a 10-digit U.S. number")
    if digits[0] in "01" or digits[3] in "01":
        raise ValueError("not a valid U.S. phone number (bad area/exchange code)")
    return digits


def normalize_state(value: Any) -> str:
    if value is None:
        raise ValueError("state is required")
    raw = str(value).strip()
    if len(raw) == 2 and raw.upper() in US_STATES:
        return raw.upper()
    mapped = STATE_NAMES.get(raw.lower())
    if mapped:
        return mapped
    raise ValueError("state must be a valid U.S. state")


def normalize_sex(value: Any) -> str:
    if value is None:
        raise ValueError("sex is required")
    raw = str(value).strip()
    if raw in SEX_VALUES:
        return raw
    mapped = SEX_ALIASES.get(raw.lower())
    if mapped:
        return mapped
    raise ValueError(f"sex must be one of: {', '.join(SEX_VALUES)}")


def normalize_dob(value: Any) -> date:
    """Accept the formats a voice agent realistically produces."""
    if value is None:
        raise ValueError("date of birth is required")
    if isinstance(value, date) and not isinstance(value, datetime):
        parsed = value
    elif isinstance(value, datetime):
        parsed = value.date()
    else:
        raw = str(value).strip()
        parsed = None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y", "%B %d, %Y",
                    "%B %d %Y", "%b %d, %Y", "%b %d %Y"):
            try:
                parsed = datetime.strptime(raw, fmt).date()
                break
            except ValueError:
                continue
        if parsed is None:
            raise ValueError("date of birth must be a real date in MM/DD/YYYY format")
    today = date.today()
    if parsed > today:
        raise ValueError("date of birth cannot be in the future")
    if parsed.year < today.year - 130:
        raise ValueError("date of birth is not plausible")
    return parsed


def normalize_zip(value: Any) -> str:
    raw = str(value).strip().replace(" ", "")
    # "941 05" or "94105 1234" from STT -> stitch back together
    if re.fullmatch(r"\d{9}", raw):
        raw = f"{raw[:5]}-{raw[5:]}"
    if not ZIP_RE.match(raw):
        raise ValueError("zip code must be 5 digits or ZIP+4")
    return raw


def normalize_name(value: Any, field: str) -> str:
    raw = str(value).strip()
    if not NAME_RE.match(raw):
        raise ValueError(
            f"{field} must be 1-50 letters (hyphens and apostrophes allowed)"
        )
    return raw


# ----------------------------------------------------------------------------
# Request / response schemas
# ----------------------------------------------------------------------------
class PatientBase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    first_name: str
    last_name: str
    date_of_birth: date
    sex: str
    phone_number: str
    address_line_1: Annotated[str, Field(min_length=1, max_length=200)]
    city: Annotated[str, Field(min_length=1, max_length=100)]
    state: str
    zip_code: str

    email: EmailStr | None = None
    address_line_2: Annotated[str | None, Field(max_length=200)] = None
    insurance_provider: Annotated[str | None, Field(max_length=120)] = None
    insurance_member_id: Annotated[str | None, Field(max_length=60)] = None
    preferred_language: Annotated[str | None, Field(max_length=50)] = "English"
    emergency_contact_name: Annotated[str | None, Field(max_length=120)] = None
    emergency_contact_phone: str | None = None

    @field_validator("first_name")
    @classmethod
    def _first(cls, v):
        return normalize_name(v, "first_name")

    @field_validator("last_name")
    @classmethod
    def _last(cls, v):
        return normalize_name(v, "last_name")

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def _dob(cls, v):
        return normalize_dob(v)

    @field_validator("sex", mode="before")
    @classmethod
    def _sex(cls, v):
        return normalize_sex(v)

    @field_validator("phone_number", mode="before")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v)

    @field_validator("emergency_contact_phone", mode="before")
    @classmethod
    def _ec_phone(cls, v):
        if v in (None, "", "null"):
            return None
        return normalize_phone(v)

    @field_validator("state", mode="before")
    @classmethod
    def _state(cls, v):
        return normalize_state(v)

    @field_validator("zip_code", mode="before")
    @classmethod
    def _zip(cls, v):
        return normalize_zip(v)

    @field_validator(
        "email", "address_line_2", "insurance_provider", "insurance_member_id",
        "emergency_contact_name", "preferred_language", mode="before",
    )
    @classmethod
    def _blank_to_none(cls, v):
        # Voice agents love sending "", "none", "N/A", "skip" for skipped fields.
        if isinstance(v, str) and v.strip().lower() in {
            "", "none", "null", "n/a", "na", "skip", "skipped", "no", "unknown",
        }:
            return None
        return v


class PatientCreate(PatientBase):
    """Payload for POST /patients."""


class PatientUpdate(BaseModel):
    """Payload for PUT /patients/:id — every field optional (partial update)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    sex: str | None = None
    phone_number: str | None = None
    email: EmailStr | None = None
    address_line_1: Annotated[str | None, Field(max_length=200)] = None
    address_line_2: Annotated[str | None, Field(max_length=200)] = None
    city: Annotated[str | None, Field(max_length=100)] = None
    state: str | None = None
    zip_code: str | None = None
    insurance_provider: Annotated[str | None, Field(max_length=120)] = None
    insurance_member_id: Annotated[str | None, Field(max_length=60)] = None
    preferred_language: Annotated[str | None, Field(max_length=50)] = None
    emergency_contact_name: Annotated[str | None, Field(max_length=120)] = None
    emergency_contact_phone: str | None = None

    @field_validator("first_name")
    @classmethod
    def _first(cls, v):
        return normalize_name(v, "first_name") if v is not None else v

    @field_validator("last_name")
    @classmethod
    def _last(cls, v):
        return normalize_name(v, "last_name") if v is not None else v

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def _dob(cls, v):
        return normalize_dob(v) if v is not None else v

    @field_validator("sex", mode="before")
    @classmethod
    def _sex(cls, v):
        return normalize_sex(v) if v is not None else v

    @field_validator("phone_number", "emergency_contact_phone", mode="before")
    @classmethod
    def _phone(cls, v):
        return normalize_phone(v) if v not in (None, "") else None

    @field_validator("state", mode="before")
    @classmethod
    def _state(cls, v):
        return normalize_state(v) if v is not None else v

    @field_validator("zip_code", mode="before")
    @classmethod
    def _zip(cls, v):
        return normalize_zip(v) if v is not None else v


class PatientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    patient_id: str
    first_name: str
    last_name: str
    date_of_birth: date
    sex: str
    phone_number: str
    email: str | None
    address_line_1: str
    address_line_2: str | None
    city: str
    state: str
    zip_code: str
    insurance_provider: str | None
    insurance_member_id: str | None
    preferred_language: str | None
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None


class Envelope(BaseModel):
    """Consistent response envelope required by the spec."""

    data: Any = None
    error: Any = None


ErrorType = Literal[
    "validation_error", "not_found", "conflict", "bad_request", "internal_error"
]
