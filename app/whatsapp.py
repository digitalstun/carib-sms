"""
WhatsApp Business Cloud API fallback for escalation ladder.

Usage: When SMS delivery fails (no delivery receipt after timeout),
escalate the same payload through WhatsApp Business API.

Requires:
- WhatsApp Business account with verified number
- Meta Business Manager with WhatsApp product enabled
- Access token from Meta for WhatsApp Business API
- Template messages pre-registered (for cold-start messages)

This module simulates/escalates. In production, set WHATSAPP_ACCESS_TOKEN env var.
"""
import os
import requests
from typing import Optional

WHATSAPP_ACCESS_TOKEN = os.environ.get("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID", "")
WHATSAPP_API_VERSION = os.environ.get("WHATSAPP_API_VERSION", "v18.0")
WHATSAPP_API_URL = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}"


def is_whatsapp_available() -> bool:
    """Check if WhatsApp Business API credentials are configured."""
    return bool(WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID)


def send_whatsapp_message(to_number: str, body: str, template_name: Optional[str] = None) -> dict:
    """
    Send WhatsApp message via WhatsApp Business Cloud API.
    Returns {"success": bool, "message_id": str, "error": str}
    """
    if not is_whatsapp_available():
        return {"success": False, "message_id": None, "error": "WhatsApp API not configured — set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID"}

    url = f"{WHATSAPP_API_URL}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    # Format number for WhatsApp API (E.164, no +)
    formatted_number = to_number.lstrip("+")

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": formatted_number,
        "type": "text",
        "text": {"body": body}
    }

    # If using a template (for 24-hour session window compliance on cold contacts)
    if template_name:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": formatted_number,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": "en", "policy": "deterministic"},
                "components": [
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": body}]
                    }
                ]
            }
        }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        data = response.json()

        if response.status_code == 200 and "messages" in data:
            msg_id = data["messages"][0]["id"]
            return {"success": True, "message_id": msg_id, "error": None}
        else:
            error_msg = data.get("error", {}).get("message", str(data))
            return {"success": False, "message_id": None, "error": f"WhatsApp API error ({response.status_code}): {error_msg}"}

    except requests.RequestException as exc:
        return {"success": False, "message_id": None, "error": f"WhatsApp request failed: {str(exc)}"}


def escalate_message(sid: str, to_number: str, body: str, template_name: Optional[str] = None) -> dict:
    """
    Main escalation entry point.
    Tries WhatsApp Business API for the given message SID.
    Returns escalation result dict.
    """
    result = send_whatsapp_message(to_number, body, template_name)
    return {
        "sid": sid,
        "escalated_to": "whatsapp" if result["success"] else "failed",
        "whatsapp_result": result,
        "timestamp": __import__("datetime").datetime.utcnow().isoformat()
    }
