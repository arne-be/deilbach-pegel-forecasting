-- migrate:up

-- Kupferdreh levels move from the Influx zero (the concrete ledge of the sewer outlet) to a
-- zero 45 cm below it, so they are never negative. 45 is level_offset_cm of kupferdreh in
-- config/pegel.json; a test keeps them in step. Rounded to 0.001 cm exactly like the ingest
-- (pegel.jobs.pipeline.ingest), so the next run sees the same values and revises nothing.
-- available_at and ingested_at stay: the readings are the same, only the datum moves.

-- The levels were negative before the shift, never after; stop instead of shifting twice.
-- An empty database passes.
DO $$
BEGIN
    IF EXISTS (SELECT FROM observations WHERE series_id = 'kupferdreh:level')
        AND NOT EXISTS (
            SELECT FROM observations WHERE series_id = 'kupferdreh:level' AND value < 0
        )
    THEN
        RAISE EXCEPTION 'kupferdreh:level has no negative values; already shifted?';
    END IF;
END
$$;

UPDATE observations o
SET value = round(o.value::numeric + 45, 3)::double precision
FROM series s
WHERE s.id = o.series_id AND s.location = 'kupferdreh' AND s.variable = 'level';

UPDATE forecast_points p
SET level_cm = round(p.level_cm::numeric + 45, 3)::double precision
FROM forecasts f
WHERE f.id = p.forecast_id AND f.station_id = 'kupferdreh';

-- migrate:down

UPDATE forecast_points p
SET level_cm = round(p.level_cm::numeric - 45, 3)::double precision
FROM forecasts f
WHERE f.id = p.forecast_id AND f.station_id = 'kupferdreh';

UPDATE observations o
SET value = round(o.value::numeric - 45, 3)::double precision
FROM series s
WHERE s.id = o.series_id AND s.location = 'kupferdreh' AND s.variable = 'level';
