-- migrate:up

-- How long after valid_at (observations) or run_at (forecasts) a series' values are
-- reliably there (measured, see docs/architecture.md). Jobs keep it in step with
-- config/pegel.json through ensure_series. Existing rows get today's config values: by
-- source, or by station where a station differs. An unknown source stops the migration
-- instead of guessing.
ALTER TABLE series ADD COLUMN available_after interval;
UPDATE series
SET available_after = CASE
    -- Langenberg sends its readings once an hour, the other LANUV gauges every few minutes.
    WHEN id = 'langenberg:level' THEN interval '75 minutes'
    WHEN source = 'influx' THEN interval '5 minutes'
    WHEN source = 'lanuv' THEN interval '15 minutes'
    WHEN source = 'radolan_rw' THEN interval '35 minutes'
    WHEN source IN ('open_meteo_icon_d2', 'open_meteo_previous_runs')
        THEN interval '120 minutes'
END;
-- Our own series derived from a gauge level, e.g. 'kupferdreh:cleaned_kalman', are computed
-- in the run that stores the level, so they are there when the level is.
UPDATE series derived
SET available_after = level.available_after
FROM series level
WHERE derived.source = 'pegel' AND level.id = derived.location || ':level';

DO $$
DECLARE
    unknown text;
BEGIN
    SELECT string_agg(id || ' (' || source || ')', ', ') INTO unknown
    FROM series
    WHERE available_after IS NULL;
    IF unknown IS NOT NULL THEN
        RAISE EXCEPTION 'series with a source of unknown delay: %', unknown;
    END IF;
END
$$;

ALTER TABLE series
    ALTER COLUMN available_after SET NOT NULL,
    ADD CHECK (available_after >= interval '0');

-- When each value was first there for us. Live runs stamp the fetch time; for old rows we
-- can't tell, so they get what a backfill gets: the first hourly run (hh:30 UTC, the
-- issue_minute in config/pegel.json) at or after valid_at or run_at plus the series'
-- available_after. Same rule as pegel.core.schedule.scheduled_available_at.
CREATE FUNCTION pg_temp.scheduled_available_at(known_at timestamptz, available_after interval)
RETURNS timestamptz LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN date_trunc('hour', known_at + available_after, 'UTC') + interval '30 minutes'
            >= known_at + available_after
        THEN date_trunc('hour', known_at + available_after, 'UTC') + interval '30 minutes'
        ELSE date_trunc('hour', known_at + available_after, 'UTC') + interval '90 minutes'
    END
$$;

ALTER TABLE observations ADD COLUMN available_at timestamptz;
UPDATE observations o
SET available_at = pg_temp.scheduled_available_at(o.valid_at, s.available_after)
FROM series s
WHERE s.id = o.series_id;
ALTER TABLE observations
    ALTER COLUMN available_at SET NOT NULL,
    ADD CHECK (available_at >= valid_at);

ALTER TABLE input_forecasts ADD COLUMN available_at timestamptz;
UPDATE input_forecasts f
SET available_at = pg_temp.scheduled_available_at(f.run_at, s.available_after)
FROM series s
WHERE s.id = f.series_id;
ALTER TABLE input_forecasts
    ALTER COLUMN available_at SET NOT NULL,
    ADD CHECK (available_at >= run_at);

-- migrate:down

ALTER TABLE input_forecasts DROP COLUMN available_at;
ALTER TABLE observations DROP COLUMN available_at;
ALTER TABLE series DROP COLUMN available_after;
