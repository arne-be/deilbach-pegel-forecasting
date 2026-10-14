"""Response bodies of the public API."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class HistoryPoint(BaseModel):
    observed_at: datetime = Field(description="UTC")
    level_cm: float = Field(description="Centimetres relative to the gauge zero; never negative")


class ForecastPointResponse(BaseModel):
    valid_at: datetime = Field(description="UTC")
    level_cm: float = Field(description="Centimetres relative to the gauge zero; never negative")


class ForecastResponse(BaseModel):
    station_id: str
    model: str
    issued_at: datetime = Field(description="When the forecast was made, UTC")
    newest_observation_at: datetime = Field(description="Newest reading it used, UTC")
    points: list[ForecastPointResponse] = Field(
        description="From one hour after the newest reading to the end of the horizon"
    )


class HistoryResponse(BaseModel):
    station_id: str
    first_day: date = Field(serialization_alias="from", description="First day, Europe/Berlin")
    last_day: date = Field(serialization_alias="to", description="Last day, included")
    observations: list[HistoryPoint] = Field(description="Raw readings, oldest first")
