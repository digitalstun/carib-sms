# CaribSMS — Hurricane-Proof SMS Failover Gateway: Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a crude prototype of an SMS failover gateway that runs on a single Android phone via Termux, accepts Twilio-compatible API calls, and dispatches SMS via the phone's cellular radio — no internet required.

**Architecture:** FastAPI server on Android/Termux with SQLite message store, three failover modes (normal/active/test), termux-sms-send dispatch, delivery receipt tracking.

**Tech Stack:** FastAPI, Python, SQLite, uvicorn, Termux API (termux-sms-send)

**Status:** Phase 1 prototype COMPLETE — all endpoints verified on macOS dev machine. Ready for Android/Termux deployment.

---

## What's Built (Phase 1 Prototype)

### Endpoints
- `GET /health` — Health check with uptime, mode, message counters
- `POST /v1/messages` — Send SMS (Twilio-compatible JSON: `to`, `body`, `From`, `status_callback`)
- `GET /v1/messages/{sid}` — Check delivery status for a message
- `GET /v1/messages` — List all messages (filterable by status, limit)
- `POST /v1/failover/activate` — Activate failover mode (live SMS dispatch)
- `POST /v1/failover/deactivate` — Deactivate failover mode (queue only)
- `POST /v1/failover/test` — Set test mode (dry-run, no actual SMS)
- `GET /v1/failover` — Get current failover state

### Failover Modes
- **normal:** Messages queued but not sent (warning logged)
- **active:** Messages dispatched via termux-sms-send immediately
- **test:** Messages marked delivered without sending (for testing)

### Database
- SQLite `messages` table: sid, to_number, from_number, body, status, direction, timestamps, error_message, carrier_ack, delivered_at
- SQLite `failover_state` table: mode, activated_at

---

## Phase 2: Android/Termux Deployment

### Prerequisites
1. Android phone with Termux installed
2. Termux:API addon installed (provides `termux-sms-send`)
3. SMS permission granted (Settings > Apps > Termux > Permissions > SMS)
4. Phone on WiFi with a known IP address

### Deployment Steps
1. Clone repo to Termux: `git clone <repo-url> ~/carib-sms`
2. Install dependencies: `pkg install python && pip install fastapi uvicorn`
3. Start server: `cd ~/carib-sms && uvicorn app.main:app --host 0.0.0.0 --port 9292`
4. Test from another device on same WiFi: `curl http://<phone-ip>:9292/health`
5. Activate failover: `curl -X POST http://<phone-ip>:9292/v1/failover/activate`
6. Send test SMS: `curl -X POST http://<phone-ip>:9292/v1/messages -H 'Content-Type: application/json' -d '{"to": "<number>", "body": "Test from CaribSMS"}'`

---

## Phase 3: Production Hardening (Future)

1. **Multi-device management** — register multiple Android phones, load balance sends
2. **Priority queue** — critical alerts jump queue, informational batch
3. **Carrier diversity** — multiple phones on different carriers (Digicel + Flow)
4. **Web dashboard** — real-time message queue, delivery stats, failover toggle
5. **WhatsApp escalation** — auto-retry failed SMS via WhatsApp Business API
6. **Ruggedized enclosure** — solar panel + battery + magnetic mount for hospital IT closets
7. **Audit trail** — compliance-ready delivery reports with timestamps, GPS, carrier ACK
8. **Billing** — per-institution subscription model ($299-$999/mo)

---

## Pitch Script (For Banks/Hospitals/ODPEM)

> "When Hurricane Beryl knocked out internet for 3 days, your cloud SMS provider went dark. Our gateway runs on a $100 Android phone with a SIM card — battery-powered, cellular-only, zero internet dependency. When the storm hits, your IT team flips a switch and critical alerts keep going through. We provide the hardware, the software, and the support. $499/month per branch."

---

## Files

| File | Purpose |
|------|---------|
| `README.md` | Project documentation |
| `requirements.txt` | Python dependencies |
| `app/__init__.py` | Package init |
| `app/main.py` | FastAPI app, all endpoints |
| `app/database.py` | SQLite setup and helpers |
| `app/schemas.py` | Pydantic request/response models |
| `app/sms.py` | SMS dispatch logic (Termux + dry-run) |
