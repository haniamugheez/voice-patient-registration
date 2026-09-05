"""Generate `vapi/assistant.json` from `vapi/system_prompt.md`.

The prompt lives in a readable markdown file (with its rationale next to it) and
this script is the single place that turns it into the JSON Vapi wants. That way
the documented prompt and the deployed prompt can never drift apart.

Usage:
    python vapi/build_assistant.py --server-url https://your-app.onrender.com
"""

import argparse
import json
import os
import pathlib
import re

HERE = pathlib.Path(__file__).parent
PROMPT_MD = HERE / "system_prompt.md"
OUT = HERE / "assistant.json"


def extract_blocks() -> tuple[str, str]:
    text = PROMPT_MD.read_text(encoding="utf-8")
    blocks = re.findall(r"```\n(.*?)```", text, flags=re.DOTALL)
    if len(blocks) < 2:
        raise SystemExit("Expected the system prompt and first message code blocks.")
    system_prompt = blocks[0].strip()
    first_message = " ".join(blocks[1].split())
    return system_prompt, first_message


PATIENT_FIELDS = {
    "first_name": {"type": "string", "description": "Caller's legal first name."},
    "last_name": {"type": "string", "description": "Caller's legal last name."},
    "date_of_birth": {
        "type": "string",
        "description": "Date of birth in MM/DD/YYYY format. Must not be in the future.",
    },
    "sex": {
        "type": "string",
        "enum": ["Male", "Female", "Other", "Decline to Answer"],
        "description": "Sex as recorded for registration.",
    },
    "phone_number": {
        "type": "string",
        "description": "10-digit U.S. phone number, digits only, no punctuation.",
    },
    "address_line_1": {"type": "string", "description": "Street address."},
    "address_line_2": {
        "type": "string",
        "description": "Apartment, suite or unit. Omit if the caller has none.",
    },
    "city": {"type": "string", "description": "City name."},
    "state": {
        "type": "string",
        "description": "Two-letter U.S. state abbreviation, e.g. CA.",
    },
    "zip_code": {"type": "string", "description": "5-digit ZIP or ZIP+4."},
    "email": {"type": "string", "description": "Email address. Omit if not given."},
    "insurance_provider": {
        "type": "string",
        "description": "Insurance company name. Omit if not given.",
    },
    "insurance_member_id": {
        "type": "string",
        "description": "Insurance member or subscriber ID. Omit if not given.",
    },
    "preferred_language": {
        "type": "string",
        "description": "Preferred spoken language. Defaults to English.",
    },
    "emergency_contact_name": {
        "type": "string",
        "description": "Emergency contact full name. Omit if not given.",
    },
    "emergency_contact_phone": {
        "type": "string",
        "description": "Emergency contact 10-digit U.S. phone number. Omit if not given.",
    },
}

REQUIRED = [
    "first_name", "last_name", "date_of_birth", "sex", "phone_number",
    "address_line_1", "city", "state", "zip_code",
]


def build(server_url: str, secret: str, model: str, voice_id: str) -> dict:
    system_prompt, first_message = extract_blocks()
    webhook = server_url.rstrip("/") + "/vapi/webhook"
    server = {"url": webhook, "secret": secret, "timeoutSeconds": 20}

    tools = [
        {
            "type": "function",
            "async": False,
            "server": server,
            "function": {
                "name": "lookup_patient",
                "description": (
                    "Check whether a patient record already exists for a phone "
                    "number. Call this once near the start of the call, before "
                    "collecting any details. Returns MATCH_FOUND with the "
                    "patient's name and patient_id, or NO_MATCH."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "phone_number": {
                            "type": "string",
                            "description": (
                                "10-digit U.S. phone number to look up. If the "
                                "caller has not given one yet, omit this and the "
                                "caller ID will be used."
                            ),
                        }
                    },
                    "required": [],
                },
            },
            "messages": [
                {
                    "type": "request-start",
                    "content": "One moment while I pull up your file.",
                }
            ],
        },
        {
            "type": "function",
            "async": False,
            "server": server,
            "function": {
                "name": "register_patient",
                "description": (
                    "Save a NEW patient registration. ONLY call this after you "
                    "have read every collected field back to the caller and they "
                    "have explicitly confirmed it is correct. Omit optional "
                    "fields the caller declined — never send empty strings or "
                    "placeholder values. The result tells you whether the save "
                    "succeeded and, if not, exactly which fields to ask about "
                    "again."
                ),
                "parameters": {
                    "type": "object",
                    "properties": PATIENT_FIELDS,
                    "required": REQUIRED,
                },
            },
            "messages": [
                {
                    "type": "request-start",
                    "content": "Great — let me get that saved for you.",
                },
                {
                    "type": "request-failed",
                    "content": (
                        "I'm sorry, our system isn't responding right now. Someone "
                        "from the office will call you back to finish this up."
                    ),
                },
            ],
        },
        {
            "type": "function",
            "async": False,
            "server": server,
            "function": {
                "name": "update_patient",
                "description": (
                    "Update an EXISTING patient record. Use this when "
                    "lookup_patient returned MATCH_FOUND and the caller agreed to "
                    "update their information. Send patient_id plus only the "
                    "fields that changed."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patient_id": {
                            "type": "string",
                            "description": "The patient_id returned by lookup_patient.",
                        },
                        **PATIENT_FIELDS,
                    },
                    "required": ["patient_id"],
                },
            },
            "messages": [
                {"type": "request-start", "content": "Updating your record now."}
            ],
        },
    ]

    return {
        "name": "Riley — Patient Intake",
        "firstMessage": first_message,
        "firstMessageMode": "assistant-speaks-first",
        "model": {
            "provider": "openai",
            "model": model,
            # Low temperature: this is data capture, not creative writing.
            "temperature": 0.3,
            "messages": [{"role": "system", "content": system_prompt}],
            "tools": tools,
        },
        "voice": {
            "provider": "11labs",
            "voiceId": voice_id,
            "stability": 0.5,
            "similarityBoost": 0.75,
        },
        "transcriber": {
            "provider": "deepgram",
            "model": "nova-2",
            "language": "en",
            # Helps the STT engine with the vocabulary this call always contains.
            "keywords": ["insurance:2", "ZIP:2", "apartment:1", "Medicare:2"],
        },
        # Let callers interrupt — corrections need to land mid-sentence.
        "backgroundSound": "office",
        "silenceTimeoutSeconds": 20,
        "responseDelaySeconds": 0.3,
        "llmRequestDelaySeconds": 0.1,
        "numWordsToInterruptAssistant": 2,
        "maxDurationSeconds": 600,
        "endCallFunctionEnabled": True,
        "endCallMessage": "Thanks again for calling. Take care.",
        "endCallPhrases": ["goodbye", "bye now", "take care"],
        "server": {"url": webhook, "secret": secret},
        "serverMessages": ["tool-calls", "end-of-call-report", "status-update"],
        "analysisPlan": {
            "summaryPrompt": (
                "In two sentences, summarise what the caller registered and "
                "whether the registration completed successfully."
            )
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--server-url",
        default=os.getenv("PUBLIC_BASE_URL", "https://YOUR-APP.onrender.com"),
        help="Public base URL of the deployed API (no trailing slash).",
    )
    parser.add_argument(
        "--secret",
        default=os.getenv("VAPI_SERVER_SECRET", "REPLACE_WITH_YOUR_SECRET"),
    )
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument(
        "--voice-id", default="21m00Tcm4TlvDq8ikWAM", help="ElevenLabs voice id."
    )
    args = parser.parse_args()

    config = build(args.server_url, args.secret, args.model, args.voice_id)
    OUT.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {OUT} (server: {args.server_url})")


if __name__ == "__main__":
    main()
