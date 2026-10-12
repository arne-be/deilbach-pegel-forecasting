-- migrate:up

-- The roles are created by hand in Neon (docs/setup-neon.md), because their
-- passwords must not live in the repo. Here they only get their permissions.
GRANT USAGE ON SCHEMA public TO pegel_jobs, pegel_api;

GRANT SELECT, INSERT, UPDATE, DELETE
    ON raw_observations, forecasts, forecast_points
    TO pegel_jobs;
GRANT USAGE ON SEQUENCE forecasts_id_seq TO pegel_jobs;

GRANT SELECT ON raw_observations, forecasts, forecast_points TO pegel_api;

-- migrate:down

REVOKE SELECT ON raw_observations, forecasts, forecast_points FROM pegel_api;
REVOKE USAGE ON SEQUENCE forecasts_id_seq FROM pegel_jobs;
REVOKE SELECT, INSERT, UPDATE, DELETE
    ON raw_observations, forecasts, forecast_points
    FROM pegel_jobs;
REVOKE USAGE ON SCHEMA public FROM pegel_jobs, pegel_api;
