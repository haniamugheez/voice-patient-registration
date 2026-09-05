# Setup guide

From an empty machine to a working phone number. ~30 minutes.

---

## 1. Push the code to GitHub

```bash
cd voice-patient-registration
git init
git add .
git commit -m "Voice AI patient registration system"
git branch -M main
git remote add origin https://github.com/<you>/voice-patient-registration.git
git push -u origin main
```

## 2. Deploy the API on Render

1. Sign in at <https://render.com> with GitHub.
2. **New → Blueprint**, pick this repository. Render reads `render.yaml` and
   creates a web service **and** a free Postgres database, wiring
   `DATABASE_URL` and generating `VAPI_SERVER_SECRET` automatically.
3. Wait for the first deploy (2–4 min), then confirm:
   - `https://<your-app>.onrender.com/health` → `{"data":{"status":"ok"},...}`
   - `https://<your-app>.onrender.com/dashboard` → two seed patients

> If you prefer not to use the blueprint: **New → Web Service**, build command
> `pip install -r requirements.txt`, start command
> `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, and set `DATABASE_URL` and
> `VAPI_SERVER_SECRET` by hand under **Environment**.

Copy the value of `VAPI_SERVER_SECRET` from **Environment** — Vapi needs it.

### Local alternative (ngrok)

If the deploy is blocked, run locally and expose it:

```bash
uvicorn app.main:app --port 8000
ngrok http 8000        # gives https://xxxx.ngrok-free.app
```

Everything below works the same with the ngrok URL — it just dies when you
close the laptop.

## 3. Generate the assistant config

```bash
python vapi/build_assistant.py \
  --server-url https://<your-app>.onrender.com \
  --secret "<VAPI_SERVER_SECRET from Render>"
```

This rewrites `vapi/assistant.json` with your URL and secret baked in.

## 4. Create the assistant in Vapi

1. Sign up at <https://vapi.ai> (free trial credit, no card needed).
2. **Assistants → Create Assistant → Blank template**.
3. Open the **JSON / raw config** view and paste the contents of
   `vapi/assistant.json`, or set the fields by hand:
   - **Model:** OpenAI `gpt-4o`, temperature `0.3`
   - **System prompt:** the fenced prompt from `vapi/system_prompt.md`
   - **First message:** the second fenced block in that file
   - **Transcriber:** Deepgram `nova-2`, English
   - **Voice:** ElevenLabs (any warm, natural voice)
4. **Tools → Create Tool** three times — `lookup_patient`, `register_patient`,
   `update_patient`. Copy each tool's name, description and parameter schema
   from `vapi/assistant.json`. For every one:
   - **Server URL:** `https://<your-app>.onrender.com/vapi/webhook`
   - **Secret:** your `VAPI_SERVER_SECRET`
   - **Async:** off
5. Attach all three tools to the assistant.
6. Under the assistant's **Advanced → Server**, set the same webhook URL and
   secret, and enable server messages `tool-calls` and `end-of-call-report`.

## 5. Buy a phone number and attach the assistant

1. **Phone Numbers → Buy Number** (a U.S. number, ~$2/month, covered by trial
   credit).
2. Under **Inbound Settings**, set the assistant to *Riley — Patient Intake*.
3. Save.

## 6. Test

Before your first real call, warm the server (Render free instances sleep):

```bash
curl https://<your-app>.onrender.com/health
```

Then call the number. A good script to try:

- Give your name, and a date of birth **in the future** — the agent should
  catch it and ask again for that field only.
- Say your last name wrong, then correct it mid-sentence.
- Decline the optional information.
- Listen for the full read-back, confirm.
- Hang up, open `/dashboard`, and see the record.
- Call again from the same number — the agent should greet you by name.

You can also test the whole data path without calling:

```bash
python scripts/simulate_call.py https://<your-app>.onrender.com
```

## 7. Fill in the README

Put the real phone number and API URL at the top of `README.md`, commit, push.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Agent says "our system isn't responding" | Render free instance was asleep and the tool call timed out | `curl /health` first; redial |
| Webhook returns 401 | Secret mismatch | The secret in Render's env must exactly equal the one on each Vapi tool |
| Tool never fires | Tool not attached to the assistant | Assistant → Tools → make sure all three are selected |
| Data gone after redeploy | Using SQLite on Render | `DATABASE_URL` must point at Postgres |
| Vapi shows a 404 on the webhook | Missing path | URL must end in `/vapi/webhook` |
| Agent invents values | Temperature too high | Keep it at 0.3 or lower |
