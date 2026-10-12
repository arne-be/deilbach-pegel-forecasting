"""Response bodies of the public API."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class HistoryPoint(BaseModel):
    observed_at: datetime = Field(description="UTC")
    level_m: float = Field(description="Metres relative to the gauge zero; can be negative")


class HistoryResponse(BaseModel):
    station_id: str
    first_day: date = Field(serialization_alias="from", description="First day, Europe/Berlin")
    last_day: date = Field(serialization_alias="to", description="Last day, included")
    observations: list[HistoryPoint] = Field(description="Raw readings, oldest first")
