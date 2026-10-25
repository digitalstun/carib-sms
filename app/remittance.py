"""
Remittance Receipt Delivery — Phase 3 PoC

Single-parish proof-of-concept for remittance receipt delivery.

Flow:
1. Remittance webhook POST /v1/remittance/receipt
   - Payload: {recipient_phone, amount_usd, sender_name, parish, transfer_id}
2. Gateway selects available Android node in parish (simulated: single device)
3. SMS dispatched via CaribSMS gateway (reuses app/sms.py)
4. Carrier delivery receipt captured
5. Webhook response: proof-of-delivery bundle

Unit economics tracked per delivery:
- Latency (ms from webhook to delivery receipt)
- Cost (simulated: JMD cost per SMS based on carrier plan)
- Carrier receipt format
- GPS coordinates (simulated: fixed parish coordinates for PoC)
"""

REMITS_PARISH_COORDS = {
    "kingston": {"lat": 17.9719, "lng": -76.7923},
    "st_andrew": {"lat": 18.0179, "lng": -76.8099},
    "st_catherine": {"lat": 17.9973, "lng": -76.9528},
    "manchester": {"lat": 18.0166, "lng": -77.5193},
}

# Simulated cost per SMS by carrier (based on Digicel/Flow prepaid rates)
CARRIER_SMS_COST_JMD = {
    "digicel": 24.0,
    "flow": 24.0,
    "clear": 20.0,
}

# Default parish if none specified
DEFAULT_PARISH = "kingston"
DEFAULT_CARRIER = "digicel"
