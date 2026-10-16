"""Response bodies of the public API."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class HistoryPoint(BaseModel):
    observed_at: datetime = Field(description="UTC")
    level_cm: float = Field(description="Centimetres relative to the gauge zero; never negative")


class BandResponse(BaseModel):
    coverage_percent: int = Field(description="The level should lie inside in this % of cases")
    lower_cm: float = Field(description="Never negative")
    upper_cm: float


class ForecastPointResponse(BaseModel):
    valid_at: datetime = Field(description="UTC")
    level_cm: float = Field(description="Centimetres relative to the gauge zero; never negative")
    bands: list[BandResponse] = Field(
        description="Uncertainty bands, narrowest first; empty past the model's last lead or "
        "for persistence"
    )


class ForecastResponse(BaseModel):
    station_id: str
    model: str
    issued_at: datetime = Field(description="When the forecast was made, UTC")
    newest_observation_at: datetime = Field(description="Newest reading it used, UTC")
    situation: str | None = Field(
        description="The situation that picked the bands, e.g. 'calm'; null without bands"
    )
    points: list[ForecastPointResponse] = Field(
        description="From one hour after the newest reading to the end of the horizon"
    )


class HistoryResponse(BaseModel):
    station_id: str
    first_day: date = Field(serialization_alias="from", description="First day, Europe/Berlin")
    last_day: date = Field(serialization_alias="to", description="Last day, included")
    observations: list[HistoryPoint] = Field(description="Raw readings, oldest first")
