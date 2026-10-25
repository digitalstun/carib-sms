import uuid
import subprocess
import sqlite3
from datetime import datetime
from app.database import get_db

def generate_sid():
    return f"SM{uuid.uuid4().hex[:32]}"

def send_sms_termux(to: str, body: str) -> dict:
    """
    Send SMS via Termux API on Android.
    Falls back to subprocess call to termux-sms-send.
    """
    try:
        result = subprocess.run(
            ["termux-sms-send", "-n", to],
            input=body,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return {"success": True, "output": result.stdout}
        else:
            return {"success": False, "error": result.stderr or "termux-sms-send failed"}
    except FileNotFoundError:
        return {"success": False, "error": "termux-sms-send not found — not running on Termux?"}
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "SMS send timed out"}

def send_sms_dry_run(to: str, body: str) -> dict:
    """
    Simulate sending SMS (for test mode).
    """
    return {"success": True, "output": f"[DRY RUN] Would send to {to}: {body[:50]}..."}

def record_delivery(db_conn, sid: str, status: str, error: str | None = None, carrier_ack: str | None = None):
    """
    Update message delivery status in SQLite.
    """
    now = datetime.utcnow().isoformat()
    if status == "delivered":
        db_conn.execute(
            "UPDATE messages SET status = ?, updated_at = ?, delivered_at = ?, error_message = ?, carrier_ack = ? WHERE sid = ?",
            (status, now, now, error, carrier_ack, sid)
        )
    else:
        db_conn.execute(
            "UPDATE messages SET status = ?, updated_at = ?, error_message = ?, carrier_ack = ? WHERE sid = ?",
            (status, now, error, carrier_ack, sid)
        )
    db_conn.commit()
