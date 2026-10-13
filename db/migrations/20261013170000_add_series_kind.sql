-- migrate:up

-- Whether a series holds observations or forecast inputs. The composite foreign
-- keys make the database reject a value written to a series of the other kind.
-- A series with values in both tables can't get one kind; stop instead of guessing.
DO $$
DECLARE
    mixed text;
BEGIN
    SELECT string_agg(id, ', ') INTO mixed
    FROM series
    WHERE id IN (SELECT series_id FROM observations)
      AND id IN (SELECT series_id FROM input_forecasts);
    IF mixed IS NOT NULL THEN
        RAISE EXCEPTION 'series with both observations and input forecasts: %', mixed;
    END IF;
END
$$;

ALTER TABLE series ADD COLUMN kind text;
-- Series that hold forecasts by others are forecasts; everything else is observed.
UPDATE series
SET kind = CASE
    WHEN id IN (SELECT series_id FROM input_forecasts) THEN 'forecast'
    ELSE 'observation'
END;
ALTER TABLE series
    ALTER COLUMN kind SET NOT NULL,
    ADD CHECK (kind IN ('observation', 'forecast')),
    ADD UNIQUE (id, kind);

ALTER TABLE observations
    ADD COLUMN kind text NOT NULL DEFAULT 'observation' CHECK (kind = 'observation'),
    DROP CONSTRAINT observations_series_id_fkey,
    ADD FOREIGN KEY (series_id, kind) REFERENCES series (id, kind);

ALTER TABLE input_forecasts
    ADD COLUMN kind text NOT NULL DEFAULT 'forecast' CHECK (kind = 'forecast'),
    DROP CONSTRAINT input_forecasts_series_id_fkey,
    ADD FOREIGN KEY (series_id, kind) REFERENCES series (id, kind);

-- migrate:down

ALTER TABLE input_forecasts
    DROP COLUMN kind,
    ADD CONSTRAINT input_forecasts_series_id_fkey FOREIGN KEY (series_id) REFERENCES series (id);

ALTER TABLE observations
    DROP COLUMN kind,
    ADD CONSTRAINT observations_series_id_fkey FOREIGN KEY (series_id) REFERENCES series (id);

ALTER TABLE series DROP COLUMN kind;
