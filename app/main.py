import time
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from pydantic import BaseModel, Field
from app.database import get_db, init_db
from app.schemas import MessageCreate, MessageResponse, HealthResponse, FailoverState, FailoverUpdate, EscalationRequest, EscalationResponse
from app.sms import generate_sid, send_sms_termux, send_sms_dry_run, record_delivery
from app.whatsapp import escalate_message as whatsapp_escalate
from app import remittance

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


# ============== Phase 3: Remittance Receipt Delivery (Single-Parish PoC) ==============

class RemittancePayload(BaseModel):
    recipient_phone: str = Field(..., description="Recipient phone number (E.164)")
    amount_usd: float = Field(..., description="Transfer amount in USD")
    sender_name: Optional[str] = Field(None, description="Sender name (optional)")
    parish: Optional[str] = Field("kingston", description="Target parish for delivery routing")
    transfer_id: str = Field(..., description="Remittance company transfer reference")
    carrier_preference: Optional[str] = Field("digicel", description="Preferred carrier: digicel, flow, or clear")

class RemittanceResponse(BaseModel):
    transfer_id: str
    recipient_phone: str
    parish: str
    message_sid: str
    status: str
    proof_of_delivery: dict
    unit_economics: dict

@app.post("/v1/remittance/receipt", response_model=RemittanceResponse)
def remittance_receipt(payload: RemittancePayload):
    """
    Phase 3: Remittance receipt delivery.
    Simulates single-parish PoC: receives webhook, sends SMS, captures delivery receipt,
    returns proof-of-delivery bundle with unit economics.
    """
    import time
    start_time = time.time()

    # Select parish coordinates
    parish = payload.parish or remittance.DEFAULT_PARISH
    coords = remittance.REMITS_PARISH_COORDS.get(parish, remittance.REMITS_PARISH_COORDS.get(remittance.DEFAULT_PARISH))

    # Generate message SID for tracking
    sid = generate_sid()

    # Build message body (remittance confirmation format)
    body = f"[CARIBSMS] Remittance Confirmed: ${payload.amount_usd:.2f} USD received. Sender: {payload.sender_name or 'Unknown'}. Ref: {payload.transfer_id}. Confirm receipt."

    # Store in DB (use existing message mechanism but tag as remittance)
    conn = get_db()
    conn.execute(
        "INSERT INTO messages (sid, to_number, from_number, body, status, direction) VALUES (?, ?, ?, ?, 'queued', 'outbound')",
        (sid, payload.recipient_phone, "CARIBSMS-REM", body)
    )
    conn.commit()

    # Simulate SMS dispatch (same mechanism as failover)
    conn.execute("SELECT mode FROM failover_state WHERE id = 1")
    mode_row = conn.execute("SELECT mode FROM failover_state WHERE id = 1").fetchone()
    mode = mode_row["mode"] if mode_row else "test"

    # For PoC: always send via simulated delivery (use dry-run to avoid burning real SMS on test)
    # In production: this would use send_sms_termux directly with real SIM
    result = send_sms_dry_run(payload.recipient_phone, body)

    if result["success"]:
        status = "delivered"
        error_msg = None
    else:
        status = "failed"
        error_msg = result.get("error", "Unknown dispatch error")

    # Calculate latency
    latency_ms = int((time.time() - start_time) * 1000)

    # Look up simulated cost
    carrier = payload.carrier_preference or remittance.DEFAULT_CARRIER
    cost_jmd = remittance.CARRIER_SMS_COST_JMD.get(carrier, 24.0)

    # Update message
    conn.execute(
        "UPDATE messages SET status = ?, updated_at = ?, error_message = ?, carrier_ack = ? WHERE sid = ?",
        (status, time.time(), error_msg, f"remit-{carrier}-po-c", sid)
    )
    conn.commit()

    # Record escalation (if needed) — not used in base remittance flow, but available
    # Build proof-of-delivery bundle
    proof = {
        "transfer_reference": payload.transfer_id,
        "message_sid": sid,
        "recipient_phone": payload.recipient_phone,
        "parish": parish,
        "coordinates": coords,
        "delivery_timestamp": time.time(),
        "delivery_latency_ms": latency_ms,
        "delivery_status": status,
        "carrier_ack": f"remit-{carrier}-po-c",
        "sim_phone_id": "android-poc-001",  # PoC: single device
        "sim_carrier": carrier,
        "sms_content_hash": sid[:8],  # simplified for PoC
        "proof_type": "simulated-single-parish"
    }

    # Unit economics
    unit_economics = {
        "cost_per_sms_jmd": cost_jmd,
        "cost_per_sms_usd": round(cost_jmd / 155.0, 4),  # Approx JMD→USD rate
        "delivery_latency_ms": latency_ms,
        "delivery_success_rate": 1.0 if status == "delivered" else 0.0,
        "parish_targeted": parish,
        "carrier_used": carrier,
        "sim_device": "android-poc-001",
        "notes": "Single-parish PoC — one Android device, simulated delivery for measurement"
    }

    conn.close()

    return RemittanceResponse(
        transfer_id=payload.transfer_id,
        recipient_phone=payload.recipient_phone,
        parish=parish,
        message_sid=sid,
        status=status,
        proof_of_delivery=proof,
        unit_economics=unit_economics
    )


@app.get("/v1/remittance/stats")
def remittance_stats():
    conn = get_db()
    # Count remittance-related messages (those with CARIBSMS-REM from_number)
    total = conn.execute("SELECT COUNT(*) as c FROM messages WHERE from_number = 'CARIBSMS-REM'").fetchone()["c"]
    delivered = conn.execute("SELECT COUNT(*) as c FROM messages WHERE from_number = 'CARIBSMS-REM' AND status = 'delivered'").fetchone()["c"]
    failed = conn.execute("SELECT COUNT(*) as c FROM messages WHERE from_number = 'CARIBSMS-REM' AND status = 'failed'").fetchone()["c"]
    queued = conn.execute("SELECT COUNT(*) as c FROM messages WHERE from_number = 'CARIBSMS-REM' AND status = 'queued'").fetchone()["c"]
    conn.close()

    # Aggregate simulated economics
    total_cost = total * remittance.CARRIER_SMS_COST_JMD.get(remittance.DEFAULT_CARRIER, 24.0)
    success_rate = delivered / total if total > 0 else 0.0

    return {
        "total_remittances": total,
        "delivered": delivered,
        "failed": failed,
        "queued": queued,
        "success_rate": round(success_rate, 2),
        "simulated_total_cost_jmd": round(total_cost, 2),
        "simulated_avg_cost_usd": round(total_cost / 155.0, 4),
        "po_c_parish": remittance.DEFAULT_PARISH,
        "po_c_carrier": remittance.DEFAULT_CARRIER,
        "po_c_notes": "Single-parish proof of concept. Real deployment requires multi-carrier Android pool."
    }


@app.get("/v1/remittance/parish/{parish}")
def remittance_parish_info(parish: str):
    """
    Returns parish-level information for delivery routing.
    Includes coordinates, supported carriers, and simulated delivery metrics.
    """
    info = remittance.REMITS_PARISH_COORDS.get(parish, remittance.REMITS_PARISH_COORDS.get(remittance.DEFAULT_PARISH))
    return {
        "parish": parish,
        "coordinates": info,
        "supported_carriers": list(remittance.CARRIER_SMS_COST_JMD.keys()),
        "delivery_pool_size": 1,  # PoC: single device
        "recommended_carrier": "digicel",
        "estimated_delivery_latency_ms": 3000,  # Simulated
        "status": "operational"
    }
