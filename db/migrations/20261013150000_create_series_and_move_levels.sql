-- migrate:up

-- What each time series is. Values live in observations and input_forecasts,
-- so a new variable needs a new series row, not a new table.
CREATE TABLE series (
    id text PRIMARY KEY,
    -- What is measured: 'level', 'rain', 'soil_moisture'.
    variable text NOT NULL,
    unit text NOT NULL,
    -- Where the values come from: 'influx', 'lanuv', 'radolan_rw', ...
    source text NOT NULL,
    -- A station or an area: 'kupferdreh', 'zone:neviges', 'catchment', ...
    location text NOT NULL,
    -- How values over an area are combined: 'mean', 'max', 'p90'. Null for one gauge.
    aggregation text,
    -- Null for a reading at one moment; otherwise the value is a total over the
    -- period ending at valid_at, e.g. '1 hour' of rain.
    period interval,
    description text NOT NULL DEFAULT ''
);

-- Everything measured: gauge levels, radar rain, soil moisture. As received,
-- so cleaning can be redone.
CREATE TABLE observations (
    series_id text NOT NULL REFERENCES series (id),
    valid_at timestamptz NOT NULL,
    value double precision NOT NULL,
    -- Share of the cells or points behind an area value that had data, 0 to 1.
    -- Null for a single gauge.
    coverage double precision,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (series_id, valid_at),
    CHECK (coverage > 0 AND coverage <= 1)
);

-- Forecasts made by others that our model uses, e.g. ICON-D2 rain. Our own
-- level forecasts stay in forecasts and forecast_points.
CREATE TABLE input_forecasts (
    series_id text NOT NULL REFERENCES series (id),
    -- Start of the weather model run. Approximate for archive sources.
    run_at timestamptz NOT NULL,
    valid_at timestamptz NOT NULL,
    value double precision NOT NULL,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (series_id, run_at, valid_at),
    CHECK (valid_at > run_at)
);

INSERT INTO series (id, variable, unit, source, location)
SELECT DISTINCT ON (station_id) station_id || ':level', 'level', 'm', source, station_id
FROM raw_observations
ORDER BY station_id, observed_at DESC;

INSERT INTO observations (series_id, valid_at, value, ingested_at)
SELECT station_id || ':level', observed_at, level_m, ingested_at
FROM raw_observations;

DROP TABLE raw_observations;

GRANT SELECT, INSERT, UPDATE, DELETE ON series, observations, input_forecasts TO pegel_jobs;
GRANT SELECT ON series, observations, input_forecasts TO pegel_api;

-- migrate:down

CREATE TABLE raw_observations (
    station_id text NOT NULL,
    observed_at timestamptz NOT NULL,
    level_m double precision NOT NULL,
    source text NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (station_id, observed_at)
);

INSERT INTO raw_observations (station_id, observed_at, level_m, source, ingested_at)
SELECT s.location, o.valid_at, o.value, s.source, o.ingested_at
FROM observations o JOIN series s ON s.id = o.series_id
WHERE s.variable = 'level';

GRANT SELECT, INSERT, UPDATE, DELETE ON raw_observations TO pegel_jobs;
GRANT SELECT ON raw_observations TO pegel_api;

DROP TABLE input_forecasts;
DROP TABLE observations;
DROP TABLE series;
