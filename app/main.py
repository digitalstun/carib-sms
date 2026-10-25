import time
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from app.database import get_db, init_db
from app.schemas import MessageCreate, MessageResponse, HealthResponse, FailoverState, FailoverUpdate, EscalationRequest, EscalationResponse
from app.sms import generate_sid, send_sms_termux, send_sms_dry_run, record_delivery
from app.whatsapp import escalate_message as whatsapp_escalate

START_TIME = time.time()

app = FastAPI(
    title="CaribSMS",
    description="Hurricane-Proof SMS Failover Gateway — runs on Android via Termux",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup():
    init_db()

@app.get("/health", response_model=HealthResponse)
def health():
    conn = get_db()
    mode_row = conn.execute("SELECT mode FROM failover_state WHERE id = 1").fetchone()
    mode = mode_row["mode"] if mode_row else "normal"
    
    sent = conn.execute("SELECT COUNT(*) as c FROM messages WHERE status = 'delivered'").fetchone()["c"]
    failed = conn.execute("SELECT COUNT(*) as c FROM messages WHERE status = 'failed'").fetchone()["c"]
    conn.close()
    
    uptime_seconds = int(time.time() - START_TIME)
    hours = uptime_seconds // 3600
    minutes = (uptime_seconds % 3600) // 60
    seconds = uptime_seconds % 60
    
    return HealthResponse(
        status="healthy",
        mode=mode,
        messages_sent=sent,
        messages_failed=failed,
        uptime=f"{hours}h {minutes}m {seconds}s"
    )

@app.post("/v1/messages", response_model=MessageResponse)
def create_message(msg: MessageCreate):
    conn = get_db()
    mode_row = conn.execute("SELECT mode FROM failover_state WHERE id = 1").fetchone()
    mode = mode_row["mode"] if mode_row else "normal"
    
    sid = generate_sid()
    
    # Insert message as queued
    conn.execute(
        "INSERT INTO messages (sid, to_number, from_number, body, status) VALUES (?, ?, ?, ?, 'queued')",
        (sid, msg.to, msg.from_, msg.body)
    )
    conn.commit()
    
    # Dispatch based on mode
    if mode == "active":
        result = send_sms_termux(msg.to, msg.body)
        if result["success"]:
            record_delivery(conn, sid, "delivered", carrier_ack="termux-ack")
        else:
            record_delivery(conn, sid, "failed", error=result["error"])
    elif mode == "test":
        result = send_sms_dry_run(msg.to, msg.body)
        record_delivery(conn, sid, "delivered", carrier_ack="dry-run")
    else:
        # Normal mode: queue but warn
        record_delivery(conn, sid, "queued", error="Failover not active — message queued")
    
    # Fetch the record
    row = conn.execute("SELECT * FROM messages WHERE sid = ?", (sid,)).fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=500, detail="Message not found after insert")
    
    return MessageResponse(
        sid=row["sid"],
        to=row["to_number"],
        from_=row["from_number"],
        body=row["body"],
        status=row["status"],
        direction=row["direction"],
        date_created=row["created_at"],
        date_updated=row["updated_at"],
        error_message=row["error_message"],
        num_segments=row["num_segments"]
    )

@app.get("/v1/messages/{message_sid}", response_model=MessageResponse)
def get_message(message_sid: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM messages WHERE sid = ?", (message_sid,)).fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Message not found")
    
    return MessageResponse(
        sid=row["sid"],
        to=row["to_number"],
        from_=row["from_number"],
        body=row["body"],
        status=row["status"],
        direction=row["direction"],
        date_created=row["created_at"],
        date_updated=row["updated_at"],
        error_message=row["error_message"],
        num_segments=row["num_segments"]
    )

@app.get("/v1/messages")
def list_messages(limit: int = 50, status: Optional[str] = None):
    conn = get_db()
    if status:
        rows = conn.execute(
            "SELECT * FROM messages WHERE status = ? ORDER BY created_at DESC LIMIT ?",
            (status, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM messages ORDER BY created_at DESC LIMIT ?",
            (limit,)
        ).fetchall()
    conn.close()
    
    return [
        MessageResponse(
            sid=r["sid"],
            to=r["to_number"],
            from_=r["from_number"],
            body=r["body"],
            status=r["status"],
            direction=r["direction"],
            date_created=r["created_at"],
            date_updated=r["updated_at"],
            error_message=r["error_message"],
            num_segments=r["num_segments"]
        )
        for r in rows
    ]

@app.post("/v1/failover/activate", response_model=FailoverState)
def activate_failover():
    conn = get_db()
    now = __import__("datetime").datetime.utcnow().isoformat()
    conn.execute(
        "UPDATE failover_state SET mode = 'active', activated_at = ? WHERE id = 1",
        (now,)
    )
    conn.commit()
    conn.close()
    return FailoverState(mode="active", activated_at=now)

@app.post("/v1/failover/deactivate", response_model=FailoverState)
def deactivate_failover():
    conn = get_db()
    conn.execute("UPDATE failover_state SET mode = 'normal', activated_at = NULL WHERE id = 1")
    conn.commit()
    conn.close()
    return FailoverState(mode="normal")

@app.post("/v1/failover/test", response_model=FailoverState)
def set_test_mode():
    conn = get_db()
    now = __import__("datetime").datetime.utcnow().isoformat()
    conn.execute(
        "UPDATE failover_state SET mode = 'test', activated_at = ? WHERE id = 1",
        (now,)
    )
    conn.commit()
    conn.close()
    return FailoverState(mode="test", activated_at=now)

@app.get("/v1/failover", response_model=FailoverState)
def get_failover_state():
    conn = get_db()
    row = conn.execute("SELECT mode, activated_at FROM failover_state WHERE id = 1").fetchone()
    conn.close()
    if not row:
        return FailoverState(mode="normal")
    return FailoverState(mode=row["mode"], activated_at=row["activated_at"])


@app.post("/v1/escalate", response_model=EscalationResponse)
def escalate(msg: EscalationRequest):
    """Escalate a failed SMS message to WhatsApp Business API."""
    conn = get_db()
    row = conn.execute("SELECT * FROM messages WHERE sid = ?", (msg.sid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Message not found")

    # Only escalate if SMS failed or is queued (not already delivered)
    if row["status"] == "delivered":
        conn.close()
        raise HTTPException(status_code=400, detail="Message already delivered via SMS — escalation not needed")

    # Call WhatsApp escalation
    result = whatsapp_escalate(
        sid=msg.sid,
        to_number=row["to_number"],
        body=row["body"],
        template_name=msg.template_name
    )

    # Record escalation in database
    conn.execute(
        "INSERT INTO escalations (sid, escalated_to, result) VALUES (?, ?, ?)",
        (msg.sid, result.get("escalated_to", "whatsapp"), str(result.get("whatsapp_result", {})))
    )
    conn.commit()

    # If WhatsApp succeeded, update message status
    if result.get("whatsapp_result", {}).get("success"):
        conn.execute(
            "UPDATE messages SET status = ?, updated_at = ?, error_message = ?, carrier_ack = ? WHERE sid = ?",
            ("delivered", __import__("datetime").datetime.utcnow().isoformat(), "Escalated to WhatsApp", "whatsapp-ack", msg.sid)
        )
    else:
        conn.execute(
            "UPDATE messages SET status = ?, updated_at = ?, error_message = ? WHERE sid = ?",
            ("failed", __import__("datetime").datetime.utcnow().isoformat(), result.get("whatsapp_result", {}).get("error", "WhatsApp escalation failed"), msg.sid)
        )
    conn.commit()
    conn.close()

    return EscalationResponse(
        sid=msg.sid,
        escalated_to=result["escalated_to"],
        result=result["whatsapp_result"]
    )


@app.get("/v1/escalations/{sid}")
def get_escalation(sid: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM escalations WHERE sid = ?", (sid,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="No escalation record found for this SID")
    return {
        "sid": row["sid"],
        "escalated_to": row["escalated_to"],
        "result": row["result"],
        "timestamp": row["timestamp"]
    }


@app.get("/v1/messages/{message_sid}/escalations")
def list_escalations_for_message(message_sid: str):
    conn = get_db()
    rows = conn.execute("SELECT * FROM escalations WHERE sid = ? ORDER BY timestamp DESC", (message_sid,)).fetchall()
    conn.close()
    return [
        {
            "sid": r["sid"],
            "escalated_to": r["escalated_to"],
            "result": r["result"],
            "timestamp": r["timestamp"]
        } for r in rows
    ]
