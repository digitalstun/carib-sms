from pydantic import BaseModel, Field
from typing import Optional

class MessageCreate(BaseModel):
    to: str = Field(..., description="Recipient phone number (E.164 format)")
    from_: Optional[str] = Field(None, alias="From", description="Sender phone number")
    body: str = Field(..., description="Message text")
    status_callback: Optional[str] = Field(None, description="Webhook URL for delivery updates")

    class Config:
        populate_by_name = True

class MessageResponse(BaseModel):
    sid: str
    to: str
    from_: Optional[str] = Field(None, alias="From")
    body: str
    status: str
    direction: str = "outbound"
    date_created: Optional[str] = None
    date_updated: Optional[str] = None
    error_message: Optional[str] = None
    num_segments: int = 1

    class Config:
        populate_by_name = True

class HealthResponse(BaseModel):
    status: str
    mode: str
    messages_sent: int
    messages_failed: int
    uptime: str

class FailoverState(BaseModel):
    mode: str
    activated_at: Optional[str] = None

class FailoverUpdate(BaseModel):
    mode: str = Field(..., description="normal, active, or test")
