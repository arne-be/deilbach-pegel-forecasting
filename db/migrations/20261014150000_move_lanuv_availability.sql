-- migrate:up

-- Nierenhof and Neviges move from 15 to 25 minutes, like Langenberg (measured 2026-10-14, see
-- README.md): Nierenhof sometimes skips a 15-minute batch, so 15 minutes let backtests use
-- values the live run didn't have yet. Rows stamped with the old scheduled slot, by a backfill
-- or by 20261013180000_add_availability, move to the first hourly run (hh:30 UTC) at or after
-- valid_at + 25 minutes. Same rule as pegel.core.schedule.scheduled_available_at.
-- The new slot is never earlier, but a live run stamps the slot in which it saw a value, so a
-- row it first saw in exactly the old slot (ingested within that slot's hour) keeps it. Rows
-- with any other available_at (live, revised) stay. Data only; a rerun changes nothing.
-- OR REPLACE: dbmate runs all migrations in one session, where earlier ones already created
-- this temp function.
CREATE OR REPLACE FUNCTION pg_temp.scheduled_available_at(known_at timestamptz, available_after interval)
RETURNS timestamptz LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        WHEN date_trunc('hour', known_at + available_after, 'UTC') + interval '30 minutes'
            >= known_at + available_after
        THEN date_trunc('hour', known_at + available_after, 'UTC') + interval '30 minutes'
        ELSE date_trunc('hour', known_at + available_after, 'UTC') + interval '90 minutes'
    END
$$;

UPDATE observations
SET available_at = pg_temp.scheduled_available_at(valid_at, interval '25 minutes')
WHERE series_id IN ('nierenhof:level', 'neviges:level')
    AND available_at = pg_temp.scheduled_available_at(valid_at, interval '15 minutes')
    AND available_at <> pg_temp.scheduled_available_at(valid_at, interval '25 minutes')
    AND NOT (ingested_at >= available_at AND ingested_at < available_at + interval '1 hour');

-- migrate:down

-- Nothing to undo: after the move a backfilled row can't be told apart from a live one.
