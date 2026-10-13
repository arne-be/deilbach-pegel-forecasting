"""Reads water levels published by LANUV NRW (live portal and open data files)."""

from datetime import UTC, datetime

from pegel.core.observations import Observation

# LANUV marks gaps with "NA" in its CSV files and with null in its JSON files.
_MISSING_VALUES = (None, "NA", "")


def parse_lanuv_value(
    station_id: str, timestamp_text: str, value: str | float | None
) -> Observation | None:
    """One LANUV reading as an observation in metres and UTC, or None for a gap.

    LANUV timestamps carry a fixed +01:00 offset all year, and values are centimetres.
    """
    observed_at = datetime.fromisoformat(timestamp_text)
    if observed_at.utcoffset() is None:
        raise ValueError(f"LANUV timestamp without offset: {timestamp_text!r}")
    if value in _MISSING_VALUES:
        return None
    return Observation(
        station_id=station_id,
        observed_at=observed_at.astimezone(UTC),
        level_m=float(value) / 100,
    )
