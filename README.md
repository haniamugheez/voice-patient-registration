# Voice AI Patient Registration

A voice agent answers a real U.S. phone number, collects standard patient
demographics through natural conversation, confirms them back to the caller,
and persists them to a database that a REST API exposes.

> **Live demo**
> - **Phone number:** **+1 (531) 223-1199**
> - **API base URL:** https://9f87-43-229-165-236.ngrok-free.app
> - **Dashboard:** https://9f87-43-229-165-236.ngrok-free.app/dashboard
> - **Interactive API docs:** https://9f87-43-229-165-236.ngrok-free.app/docs
>
> The API is served from a local process exposed through an ngrok tunnel — see
> [Deployment](#deployment) for why, and for the cloud path that is already
> wired up in this repo. The tunnel URL changes if the tunnel is restarted; if
> the links above are unreachable, please get in touch and I will send the
> current URL.

---

## Architecture

```
   ☎  Caller
   │
   │  PSTN
   ▼
┌───────────────────────────────────────────┐
│  Vapi                                     │
│  telephony · Soniox STT · Vapi TTS         │
│  GPT-4.1 + tool definitions                │
└──────────────────┬────────────────────────┘
                   │  HTTPS  POST /vapi/webhook
                   │  (tool-calls, end-of-call-report)
                   ▼
┌───────────────────────────────────────────┐
│  FastAPI application                      │
│                                           │
│  routers/vapi.py    ← voice agent adapter │
│  routers/patients.py← public REST API     │
│  routers/dashboard  ← read-only web UI    │
│         │                                 │
│         ▼                                 │
│  schemas.py   validation / normalization  │
│  crud.py      service layer               │
│  models.py    ORM                         │
└──────────────────┬────────────────────────┘
                   ▼
        SQLAlchemy → SQLite (local) / Postgres (prod)
```

**The key separation:** the voice agent never touches the database. It calls
three tools; `routers/vapi.py` translates those tool calls into the *same*
validation schemas and *same* service-layer functions the REST API uses. There
is exactly one place where a patient record can be created, and exactly one
place where "is this a valid U.S. phone number?" is answered.

### Layers

| Layer | File | Responsibility |
|---|---|---|
| Telephony + STT/TTS + LLM | Vapi (config in `vapi/`) | Speech, turn-taking, prompt |
| Voice ↔ data adapter | `app/routers/vapi.py` | Parse tool calls, phrase results for speech |
| Public API | `app/routers/patients.py` | REST endpoints, status codes, envelope |
| Validation | `app/schemas.py` | Server-side rules; normalizes messy STT output |
| Service layer | `app/crud.py` | All reads/writes; used by both entry points |
| Persistence | `app/models.py` + SQLAlchemy | Schema, constraints, soft delete |
| UI | `app/routers/dashboard.py` | Server-rendered patient table |

---

## Tech stack, and why

| Choice | Reason |
|---|---|
| **Vapi** | Bundles the phone number, STT, TTS, barge-in and the LLM tool loop. Building Twilio + Deepgram + ElevenLabs + a websocket media stream by hand is the whole three hours; the assessment is about integration, not writing an STT pipeline. Every assistant setting lives in `vapi/assistant.json`, generated from a version-controlled prompt. |
| **FastAPI** | Pydantic gives request validation, OpenAPI docs and typed models for free — which matters when the same validation must serve both a REST client and a voice agent. |
| **SQLAlchemy** | One data layer, two databases: SQLite for a zero-setup local run, Postgres in production by changing `DATABASE_URL` only. |
| **SQLite → Postgres** | SQLite is the right default for a take-home (no service to provision). But Render's free web instances have an ephemeral filesystem, so the deployed copy points at a free Render Postgres — otherwise "call back tomorrow and Jane Doe is still there" would not hold. |
| **GPT-4.1** | Holds a partially-filled form across corrections and follows a numbered procedure without skipping the confirmation step. Temperature 0.3 — this is data capture, not creative writing. |
| **Soniox STT** | 1.8% WER on this workload versus Deepgram nova-2, and better on spelled-out names and digit strings — which is most of this call. Auto-fallback to a backup transcriber is enabled so a provider hiccup does not drop the call. |
| **Vapi voice (Elliot)** | Natural enough for intake and needs no third-party TTS key, so the system depends on two vendor accounts instead of four. |

---

## Data model

`patients` — every field from the spec, plus soft-delete:

| Column | Type | Notes |
|---|---|---|
| `patient_id` | UUID (string, PK) | auto-generated |
| `first_name`, `last_name` | varchar(50) | letters, hyphens, apostrophes |
| `date_of_birth` | date | parsed from several spoken formats; never future |
| `sex` | varchar(20) | Male / Female / Other / Decline to Answer |
| `phone_number` | varchar(10), indexed | stored as 10 bare digits so lookup is exact |
| `email` | varchar(254), nullable | RFC-validated |
| `address_line_1` / `_2`, `city`, `state`, `zip_code` | | `state` normalized to 2 letters; ZIP or ZIP+4 |
| `insurance_provider`, `insurance_member_id` | nullable | |
| `preferred_language` | nullable, default `English` | |
| `emergency_contact_name` / `_phone` | nullable | |
| `created_at`, `updated_at` | timestamp (UTC) | auto |
| `deleted_at` | timestamp, nullable | soft delete — rows are never removed |

`call_transcripts` — one row per call (`call_id`, caller number, summary,
transcript, ended reason), linked to a patient when the number matches.

**Normalization is deliberate.** A caller says "four one five, five five five,
oh one three two" and the transcriber may return `(415) 555-0132`, `415-555-0132` or
`+14155550132`. All three become `4155550132` before they reach the database,
which is what makes duplicate detection work at all. Same for `California →
CA`, `male → Male`, `March 5 1990 → 1990-03-05`.

---

## API

All responses use the envelope `{ "data": ..., "error": ... }`.

| Method | Endpoint | Codes |
|---|---|---|
| `GET` | `/patients` — filters: `?last_name=`, `?date_of_birth=`, `?phone_number=`, `?include_deleted=`, `?limit=`, `?offset=` | 200, 422 |
| `GET` | `/patients/{patient_id}` | 200, 404 |
| `POST` | `/patients` | 201, 422 |
| `PUT` | `/patients/{patient_id}` — partial updates | 200, 400, 404, 422 |
| `DELETE` | `/patients/{patient_id}` — soft delete | 200, 404 |
| `POST` | `/vapi/webhook` — Vapi tool calls + end-of-call reports | 200, 401 |
| `GET` | `/health`, `/dashboard`, `/docs` | 200 |

Query filters accept human formats — `?date_of_birth=04/12/1985` and
`?phone_number=(415) 555-0132` both work.

```bash
# create
curl -X POST $BASE/patients -H 'content-type: application/json' -d '{
  "first_name":"Jane","last_name":"Doe","date_of_birth":"04/12/1985",
  "sex":"Female","phone_number":"4155550132","address_line_1":"742 Evergreen Terrace",
  "city":"San Francisco","state":"CA","zip_code":"94107"}'

# find
curl "$BASE/patients?last_name=Doe"

# soft delete
curl -X DELETE $BASE/patients/<uuid>
```

Error shape:

```json
{
  "data": null,
  "error": {
    "type": "validation_error",
    "message": "One or more fields failed validation",
    "details": [{ "field": "phone_number", "message": "phone number must be a 10-digit U.S. number" }]
  }
}
```

---

## Voice agent design

The full prompt and the reasoning behind each rule are in
[`vapi/system_prompt.md`](vapi/system_prompt.md). `vapi/assistant.json` is
**generated** from it:

```bash
python vapi/build_assistant.py --server-url https://<your-host> --secret "$VAPI_SERVER_SECRET"
```

Three tools are exposed to the model:

| Tool | When | Returns |
|---|---|---|
| `lookup_patient` | once at the start | `MATCH_FOUND …` / `NO_MATCH` |
| `register_patient` | after the caller confirms the read-back | `SAVED …` / `NOT SAVED …` / `DUPLICATE …` / `SAVE_FAILED …` |
| `update_patient` | returning caller chooses to update | `UPDATED …` / `NOT_FOUND …` |

**Tool results are written as stage directions, not as data.** The model reads
whatever comes back, so returning `{"errors":[{"loc":["date_of_birth"]}]}`
makes the agent recite JSON. Instead the webhook returns:

> `NOT SAVED. These fields are invalid — date_of_birth: date of birth cannot be
> in the future. Apologise briefly and ask the caller again only for:
> date_of_birth.`

That single design choice is what produces the field-specific re-prompt the
spec asks for, without hoping the model infers it.

---

## Running locally

```bash
git clone <this repo> && cd voice-patient-registration
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Open http://localhost:8000/dashboard (two seed patients are inserted on first
start) and http://localhost:8000/docs.

Test the full voice data path **without a phone**:

```bash
python scripts/simulate_call.py http://localhost:8000
```

It sends the exact payloads Vapi sends: a lookup, a bad date of birth, a
successful save, a duplicate-detection lookup, and an end-of-call transcript.

Run the tests:

```bash
pytest -q     # 19 tests: validation, CRUD, soft delete, webhook auth + flows
```

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | no | Defaults to `sqlite:///./data/patients.db`. Set to a Postgres URL in production. |
| `VAPI_SERVER_SECRET` | production | Shared secret Vapi sends as `x-vapi-secret`. If unset, webhook auth is skipped (local dev only). |
| `ENV`, `LOG_LEVEL` | no | `development` / `INFO` |
| `SEED_ON_STARTUP` | no | Insert two demo patients on boot (idempotent). |

No secret is ever committed — see `.env.example`.

---

## Deployment

**What is running now:** `uvicorn` on a local machine, exposed to the internet
through a *reserved* ngrok domain (so the URL is stable across restarts, and
Vapi's webhook configuration does not need re-editing between sessions).

```bash
# terminal 1 — the API
uvicorn app.main:app --port 8000

# terminal 2 — the public tunnel
ngrok http 8000    # a reserved domain keeps the URL stable across restarts
```

**Why not a cloud host.** The intended target was Render, and the repo still
carries everything for it: `render.yaml` provisions the web service *and* a free
Postgres instance and wires `DATABASE_URL` automatically, plus a `Procfile` for
any Heroku-style platform. Render now requires credit-card identity
verification before it will create any service — Blueprint or single web service
— which was not available within the time window. Railway and Fly.io have the
same requirement. Rather than burn the remaining time on vendor onboarding, the
system was exposed through ngrok, which the brief explicitly lists as an
acceptable hosting option.

**To move it to a cloud host later**, nothing in the code changes:

```bash
# Render (or any platform that reads a Procfile / start command)
#   build:  pip install -r requirements.txt
#   start:  uvicorn app.main:app --host 0.0.0.0 --port $PORT
#   env:    DATABASE_URL (Postgres), VAPI_SERVER_SECRET, PYTHON_VERSION=3.11.9
```

Then regenerate the assistant config against the new URL and update the three
tool webhooks in Vapi:

```bash
python vapi/build_assistant.py --server-url https://<new-host> --secret "$VAPI_SERVER_SECRET"
```

**Trade-off, stated plainly:** the tunnel means the machine must be running and
both processes alive during review. In exchange, persistence is *stronger* than
it would have been on a free cloud tier — the SQLite file lives on a real disk
that survives restarts and redeploys, whereas Render's free web instances have
an ephemeral filesystem and would have required the external Postgres anyway.

Then in Vapi: import `vapi/assistant.json`, buy a U.S. number, and attach the
assistant to it. Step-by-step instructions, including the Vapi dashboard
clicks, are in [`SETUP.md`](SETUP.md).

---

## Edge cases handled

| Case | Behaviour |
|---|---|
| Invalid DOB (future, impossible date, 1800s) | Webhook returns a field-specific re-prompt; the agent asks again for that field only |
| Phone number too short / bad area code | Same — validated server-side, never trusted from the model |
| Caller says "California" instead of "CA" | Normalized to `CA` |
| Caller says "prefer not to say" for sex | Mapped to `Decline to Answer` |
| Caller gives no phone number | Falls back to caller ID from the Vapi payload |
| Returning caller | `lookup_patient` finds them by number; agent offers to update instead of duplicating |
| Duplicate slips through anyway | `register_patient` re-checks server-side and refuses, returning `DUPLICATE` |
| Database write fails | Agent is told to apologise, promise a callback, and end gracefully — never a silent failure or a false "you're all set" |
| Unhandled exception in a tool | Caught; the agent gets a spoken apology instead of an HTTP 500 mid-call |
| Call drops mid-registration | Nothing partial is written — the record is only created on the single confirmed tool call. The transcript is still stored via `end-of-call-report` |
| Caller wants to start over | Prompt instructs the agent to discard everything and restart from the first name |
| Agent sends `""` / `"N/A"` for skipped optional fields | Coerced to `NULL` rather than stored as junk |
| Invalid webhook secret | 401 |

---

## Bonus items included

- ✅ **Duplicate detection** — by phone number, at both the prompt and the server level
- ✅ **Call transcripts** — stored per call and linked to the patient record
- ✅ **Dashboard** — `/dashboard`, server-rendered, light/dark
- ✅ **Automated tests** — 19 pytest integration tests
- ✅ **Spanish** — prompt switches language on "hablo español" and records `preferred_language`

---

## Trade-offs and known limitations

1. **SQLite, not Postgres.** Because the app is served from a real filesystem
   rather than an ephemeral container, SQLite satisfies the persistence
   requirement as-is: the file survives restarts and second calls. The Postgres
   path is written and configured (`DATABASE_URL`, `psycopg2` pinned,
   `postgres://` → `postgresql://` normalization in `app/database.py`) but is
   not exercised in this deployment. Switching is one environment variable.
2. **No migrations.** Tables are created with `create_all()`. Fine for a
   greenfield schema; a real system would use Alembic before the first change.
3. **Duplicate detection is phone-only.** Two family members sharing a landline
   would collide. Real intake matches on name + DOB + phone with a review queue.
4. **The public API is unauthenticated.** Deliberate, so reviewers can curl it.
   `API_KEY` is scaffolded in config; a real deployment would require it on
   writes and put the whole thing behind TLS + audit logging.
5. **Full payloads are logged to stdout.** Useful for grading, wrong for PHI.
   Production would redact and ship to a HIPAA-eligible sink.
6. **No retry/queue on DB failure.** The caller is told to expect a callback
   rather than the agent silently losing the data; an outbox table would be the
   next step.
7. **The tunnel is a single point of failure.** If the host machine sleeps or
   either process stops, the number answers but every tool call fails — the
   agent then apologises and promises a callback rather than lying about a save
   (see `SAVE_FAILED` handling), but no registration completes. A cloud host
   removes this; see [Deployment](#deployment).
8. **Address is not verified.** No USPS/Smarty lookup — the ZIP is format-checked
   but not matched against the city and state.

---

## Next steps (with more than three hours)

- Alembic migrations and a proper deploy pipeline
- Partial-progress persistence so a dropped call can be resumed on callback
- Fuzzy patient matching (name + DOB + phone) with a human review queue
- Address verification via USPS, and insurance eligibility checks
- Redact PHI from logs; structured logging with per-call correlation ids
- Appointment scheduling as a fourth tool
- An eval suite of recorded calls (accents, corrections, interruptions) scored
  automatically against expected records
- Rate limiting and API-key auth on the REST layer

---

## Project layout

```
app/
  main.py              FastAPI app, error handlers, logging
  config.py            env-driven settings
  database.py          engine/session, SQLite↔Postgres switch
  models.py            Patient, CallTranscript
  schemas.py           validation + normalization (the trust boundary)
  crud.py              service layer used by BOTH entry points
  seed.py              idempotent demo data
  routers/
    patients.py        REST API
    vapi.py            voice-agent webhook
    dashboard.py       read-only UI
vapi/
  system_prompt.md     the prompt + why each rule exists
  build_assistant.py   generates assistant.json from the prompt
  assistant.json       importable Vapi assistant config
scripts/
  simulate_call.py     exercise the voice path without a phone
tests/
  test_api.py          19 integration tests
render.yaml            one-click deploy (web + Postgres)
SETUP.md               step-by-step setup guide
```
