-- migrate:up

-- Grafana Cloud reads prod for the dashboards in grafana/dashboards/. The role is
-- created by hand in Neon (docs/setup-neon.md), like the others.
GRANT USAGE ON SCHEMA public TO pegel_grafana;
GRANT SELECT ON series, observations, input_forecasts, forecasts, forecast_points TO pegel_grafana;

-- migrate:down

REVOKE SELECT ON series, observations, input_forecasts, forecasts, forecast_points FROM pegel_grafana;
REVOKE USAGE ON SCHEMA public FROM pegel_grafana;
