-- migrate:up

-- How long after valid_at (observations) or run_at (forecasts) each series' values are
-- reliably there (measured, see docs/architecture.md), copied from config/pegel.json; a test
-- keeps them in step. Gauge levels by series id, other sources by source. Our own series
-- derived from a gauge level, e.g. 'kupferdreh:cleaned_kalman', are computed in the run that
-- stores the level, so they get the level's delay. Only to fill existing rows: jobs take the
-- delay from config. A series of unknown delay stops the migration instead of guessing.
CREATE TEMP TABLE series_delay ON COMMIT DROP AS
SELECT series.id, series.source, delay.available_after
FROM series
LEFT JOIN (VALUES
    ('kupferdreh:level', interval '5 minutes'),
    -- Langenberg sends its readings once an hour, the other LANUV gauges every few minutes.
    ('langenberg:level', interval '75 minutes'),
    ('neviges:level', interval '15 minutes'),
    ('nierenhof:level', interval '15 minutes'),
    ('radolan_rw', interval '35 minutes'),
    ('open_meteo_icon_d2', interval '120 minutes'),
    ('open_meteo_previous_runs', interval '120 minutes')
) AS delay (key, available_after) ON delay.key = CASE
    WHEN series.source = 'pegel' THEN series.location || ':level'
    WHEN series.source IN ('influx', 'lanuv') THEN series.id
    ELSE series.source
END;

DO $$
DECLARE
    unknown text;
BEGIN
    SELECT string_agg(id || ' (' || source || ')', ', ') INTO unknown
    FROM series_delay
    WHERE available_after IS NULL;
    IF unknown IS NOT NULL THEN
        RAISE EXCEPTION 'series of unknown delay: %', unknown;
    END IF;
END
$$;

-- When each value was first there for us. Live runs stamp the fetch time; for old rows we
-- can't tell, so they get what a backfill gets: the first hourly run (hh:30 UTC, the
-- issue_minute in config/pegel.json) at or after valid_at or run_at plus the series'
-- delay. Same rule as pegel.core.schedule.scheduled_available_at.
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
FROM series_delay s
WHERE s.id = o.series_id;
ALTER TABLE observations
    ALTER COLUMN available_at SET NOT NULL,
    ADD CHECK (available_at >= valid_at);

ALTER TABLE input_forecasts ADD COLUMN available_at timestamptz;
UPDATE input_forecasts f
SET available_at = pg_temp.scheduled_available_at(f.run_at, s.available_after)
FROM series_delay s
WHERE s.id = f.series_id;
ALTER TABLE input_forecasts
    ALTER COLUMN available_at SET NOT NULL,
    ADD CHECK (available_at >= run_at);

-- migrate:down

ALTER TABLE input_forecasts DROP COLUMN available_at;
ALTER TABLE observations DROP COLUMN available_at;
