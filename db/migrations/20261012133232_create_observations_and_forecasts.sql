-- migrate:up

-- Levels as received from the source, already in metres. Cleaning derives
-- from this table later, so it keeps every value, including negative ones.
CREATE TABLE raw_observations (
    station_id text NOT NULL,
    observed_at timestamptz NOT NULL,
    level_m double precision NOT NULL,
    source text NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (station_id, observed_at)
);

CREATE TABLE forecasts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    station_id text NOT NULL,
    model text NOT NULL,
    issued_at timestamptz NOT NULL,
    newest_observation_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    -- The natural key: a rerun for the same hour replaces, never duplicates.
    UNIQUE (station_id, model, issued_at)
);

CREATE TABLE forecast_points (
    forecast_id bigint NOT NULL REFERENCES forecasts (id) ON DELETE CASCADE,
    valid_at timestamptz NOT NULL,
    level_m double precision NOT NULL,
    PRIMARY KEY (forecast_id, valid_at)
);

-- migrate:down

DROP TABLE forecast_points;
DROP TABLE forecasts;
DROP TABLE raw_observations;
