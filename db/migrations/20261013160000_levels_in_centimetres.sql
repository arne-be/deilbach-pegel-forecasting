-- migrate:up

-- Levels in centimetres, as LANUV delivers them and people read them.
-- Rounded to 0.001 cm: the finest step either source has (LANUV files carry
-- up to three decimals of a cm, Influx whole mm), so no value changes beyond
-- removing float noise such as 22.900000000000002.
UPDATE observations o
SET value = round((o.value * 100)::numeric, 3)::double precision
FROM series s
WHERE s.id = o.series_id AND s.variable = 'level' AND s.unit = 'm';

UPDATE series SET unit = 'cm' WHERE variable = 'level' AND unit = 'm';

ALTER TABLE forecast_points RENAME COLUMN level_m TO level_cm;
UPDATE forecast_points SET level_cm = round((level_cm * 100)::numeric, 3)::double precision;

-- migrate:down

UPDATE forecast_points SET level_cm = round((level_cm / 100)::numeric, 5)::double precision;
ALTER TABLE forecast_points RENAME COLUMN level_cm TO level_m;

UPDATE observations o
SET value = round((o.value / 100)::numeric, 5)::double precision
FROM series s
WHERE s.id = o.series_id AND s.variable = 'level' AND s.unit = 'cm';

UPDATE series SET unit = 'm' WHERE variable = 'level' AND unit = 'cm';
