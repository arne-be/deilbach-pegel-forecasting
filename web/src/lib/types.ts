// Mirrors the API responses in src/pegel/api/schemas.py; field names as in the JSON.
// Times are UTC ISO strings, levels centimetres relative to the gauge zero.

export interface Band {
  coverage_percent: number;
  lower_cm: number;
  upper_cm: number;
}

export interface ForecastPoint {
  valid_at: string;
  level_cm: number;
  /** Narrowest first; empty past the model's last lead or for persistence. */
  bands: Band[];
}

export interface ForecastResponse {
  station_id: string;
  model: string;
  issued_at: string;
  newest_observation_at: string;
  situation: string | null;
  points: ForecastPoint[];
}

export interface HistoryPoint {
  observed_at: string;
  level_cm: number;
}

export interface HistoryResponse {
  station_id: string;
  /** First day, Europe/Berlin, `YYYY-MM-DD`. */
  from: string;
  /** Last day, included. */
  to: string;
  /** Oldest first. */
  observations: HistoryPoint[];
}
