-- migrate:up

-- The situation a model forecast was made in (e.g. 'dry'), which picks its uncertainty
-- bands. Null for persistence and for forecasts made before bands existed.
ALTER TABLE forecasts ADD COLUMN situation text;

-- Uncertainty bands around a forecast point: the observed level should lie between lower_cm
-- and upper_cm in coverage_percent of cases, from past errors of the same model.
CREATE TABLE forecast_bands (
    forecast_id bigint NOT NULL,
    valid_at timestamptz NOT NULL,
    coverage_percent integer NOT NULL,
    lower_cm double precision NOT NULL,
    upper_cm double precision NOT NULL,
    PRIMARY KEY (forecast_id, valid_at, coverage_percent),
    FOREIGN KEY (forecast_id, valid_at)
        REFERENCES forecast_points (forecast_id, valid_at) ON DELETE CASCADE,
    CHECK (coverage_percent > 0 AND coverage_percent < 100),
    CHECK (lower_cm <= upper_cm)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON forecast_bands TO pegel_jobs;
GRANT SELECT ON forecast_bands TO pegel_api, pegel_grafana;

-- migrate:down

DROP TABLE forecast_bands;
ALTER TABLE forecasts DROP COLUMN situation;
