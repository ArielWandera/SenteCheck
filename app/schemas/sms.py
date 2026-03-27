from datetime import datetime
from typing import Literal

from pydantic import BaseModel, field_validator


class SMSPayload(BaseModel):
    telegram_id: int
    raw_sms: str
    received_at: datetime
    sim: Literal["MTN", "Airtel"]

    @field_validator("telegram_id")
    @classmethod
    def must_be_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("telegram_id must be a positive integer")
        return v

    @field_validator("raw_sms")
    @classmethod
    def max_length(cls, v: str) -> str:
        if len(v) > 1000:
            raise ValueError("SMS body must not exceed 1000 characters")
        return v


class WebhookResponse(BaseModel):
    status: str
    action: str  # "logged" | "classification_requested" | "ignored"
    transaction_id: int | None = None
