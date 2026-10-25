# CaribSMS — Hurricane-Proof SMS Failover Gateway

A crude prototype: FastAPI-based SMS gateway that runs on a single Android phone via Termux. Accepts Twilio-compatible API calls and dispatches SMS via the phone's cellular radio — no internet required.

## Purpose

When a hurricane knocks out internet or cloud regions, banks, hospitals, and emergency services in Jamaica/Caribbean lose their cloud SMS providers (Twilio, AWS SNS). This gateway runs on battery + local cell towers and keeps sending critical alerts.

## Architecture

```
[Client App] --POST /v1/messages--> [FastAPI on Android/Termux] --SmsManager--> [Cellular Network] --> [Recipient Phone]
         ^                                    |
         |                                    v
         +-------GET /v1/messages/<id>-------- [SQLite: delivery receipts]
```

## Quick Start (Local Dev)

```bash
cd ~/production/carib-sms
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 9292
```

## Quick Start (Termux on Android)

```bash
pkg install python
pip install fastapi uvicorn httpx sqlite3
cd ~/carib-sms
uvicorn app.main:app --host 0.0.0.0 --port 9292
```

## API Endpoints

- `POST /v1/messages` — Send SMS (Twilio-compatible)
- `GET /v1/messages/{message_sid}` — Check delivery status
- `GET /health` — Health check
- `POST /v1/failover/activate` — Activate failover mode
- `POST /v1/failover/deactivate` — Deactivate failover mode

## Failover Modes

- **Normal:** Gateway accepts messages but logs a warning that failover is not active
- **Active:** Gateway dispatches messages immediately via cellular radio
- **Test:** Gateway queues messages but doesn't send (for testing without burning SMS)

## License

Apache-2.0
