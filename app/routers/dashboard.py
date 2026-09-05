"""Bonus: a tiny read-only dashboard so reviewers can see the data in a browser.

Server-rendered on purpose — no build step, no client framework, one request.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import crud
from app.database import get_db
from app.models import CallTranscript

router = APIRouter(tags=["dashboard"])

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Patient Registry</title>
<style>
  :root {{ color-scheme: light dark; --bg:#f7f7f5; --card:#fff; --ink:#1a1a18;
           --muted:#6b6b66; --line:#e5e5e0; --accent:#0f6b5c; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#131312; --card:#1c1c1a; --ink:#ececea; --muted:#9a9a94;
             --line:#2c2c29; --accent:#4dd0b1; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.5
         ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:1200px; margin:0 auto; padding:32px 20px 64px; }}
  h1 {{ font-size:22px; margin:0 0 4px; letter-spacing:-.01em; }}
  .sub {{ color:var(--muted); margin:0 0 24px; }}
  .stats {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:24px; }}
  .stat {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
           padding:14px 18px; min-width:130px; }}
  .stat b {{ display:block; font-size:24px; font-weight:600; }}
  .stat span {{ color:var(--muted); font-size:12px; text-transform:uppercase;
                letter-spacing:.06em; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
           overflow-x:auto; margin-bottom:28px; }}
  table {{ border-collapse:collapse; width:100%; min-width:900px; }}
  th, td {{ text-align:left; padding:10px 14px; border-bottom:1px solid var(--line);
            white-space:nowrap; }}
  th {{ font-size:11px; text-transform:uppercase; letter-spacing:.06em;
        color:var(--muted); font-weight:600; }}
  tr:last-child td {{ border-bottom:none; }}
  code {{ font-size:12px; color:var(--muted); }}
  h2 {{ font-size:15px; margin:0 0 10px; }}
  .empty {{ padding:28px; color:var(--muted); text-align:center; }}
  a {{ color:var(--accent); }}
</style></head><body><div class="wrap">
<h1>Patient Registry</h1>
<p class="sub">Records collected by the voice agent &middot;
   <a href="/docs">API docs</a></p>
<div class="stats">
  <div class="stat"><b>{count}</b><span>Patients</span></div>
  <div class="stat"><b>{calls}</b><span>Calls logged</span></div>
</div>
<div class="card">{table}</div>
<h2>Recent calls</h2>
<div class="card">{transcripts}</div>
</div></body></html>"""


def _esc(v) -> str:
    if v is None:
        return "—"
    return (
        str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _fmt_phone(p: str | None) -> str:
    if not p or len(p) != 10:
        return _esc(p)
    return f"({p[:3]}) {p[3:6]}-{p[6:]}"


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard(db: Session = Depends(get_db)):
    patients = crud.list_patients(db, limit=500)
    calls = list(
        db.execute(
            select(CallTranscript).order_by(CallTranscript.created_at.desc()).limit(20)
        ).scalars().all()
    )

    if patients:
        head = (
            "<tr><th>Name</th><th>DOB</th><th>Sex</th><th>Phone</th><th>Address</th>"
            "<th>Insurance</th><th>Emergency contact</th><th>Registered</th>"
            "<th>Patient ID</th></tr>"
        )
        rows = []
        for p in patients:
            addr = f"{p.address_line_1}"
            if p.address_line_2:
                addr += f", {p.address_line_2}"
            addr += f", {p.city}, {p.state} {p.zip_code}"
            ins = p.insurance_provider or ""
            if p.insurance_member_id:
                ins += f" ({p.insurance_member_id})"
            ec = p.emergency_contact_name or ""
            if p.emergency_contact_phone:
                ec += f" {_fmt_phone(p.emergency_contact_phone)}"
            rows.append(
                "<tr>"
                f"<td><strong>{_esc(p.first_name)} {_esc(p.last_name)}</strong></td>"
                f"<td>{p.date_of_birth.strftime('%m/%d/%Y')}</td>"
                f"<td>{_esc(p.sex)}</td>"
                f"<td>{_fmt_phone(p.phone_number)}</td>"
                f"<td>{_esc(addr)}</td>"
                f"<td>{_esc(ins or None)}</td>"
                f"<td>{_esc(ec or None)}</td>"
                f"<td>{p.created_at.strftime('%Y-%m-%d %H:%M')} UTC</td>"
                f"<td><code>{_esc(p.patient_id)}</code></td>"
                "</tr>"
            )
        table = f"<table>{head}{''.join(rows)}</table>"
    else:
        table = '<div class="empty">No patients yet — call the number to register one.</div>'

    if calls:
        crows = "".join(
            "<tr>"
            f"<td>{c.created_at.strftime('%Y-%m-%d %H:%M')} UTC</td>"
            f"<td>{_esc(c.caller_number)}</td>"
            f"<td>{_esc(c.ended_reason)}</td>"
            f"<td>{_esc((c.summary or '')[:180] or None)}</td>"
            "</tr>"
            for c in calls
        )
        transcripts = (
            "<table><tr><th>When</th><th>Caller</th><th>Ended</th><th>Summary</th></tr>"
            f"{crows}</table>"
        )
    else:
        transcripts = '<div class="empty">No calls recorded yet.</div>'

    return HTMLResponse(
        PAGE.format(
            count=len(patients), calls=len(calls), table=table, transcripts=transcripts
        )
    )
