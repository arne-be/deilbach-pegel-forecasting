\restrict dbmate

-- Dumped from database version 17.11
-- Dumped by pg_dump version 18.6

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: forecast_points; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.forecast_points (
    forecast_id bigint NOT NULL,
    valid_at timestamp with time zone NOT NULL,
    level_cm double precision NOT NULL
);


--
-- Name: forecasts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.forecasts (
    id bigint NOT NULL,
    station_id text NOT NULL,
    model text NOT NULL,
    issued_at timestamp with time zone NOT NULL,
    newest_observation_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: forecasts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.forecasts ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.forecasts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: input_forecasts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.input_forecasts (
    series_id text NOT NULL,
    run_at timestamp with time zone NOT NULL,
    valid_at timestamp with time zone NOT NULL,
    value double precision NOT NULL,
    fetched_at timestamp with time zone DEFAULT now() NOT NULL,
    kind text DEFAULT 'forecast'::text NOT NULL,
    available_at timestamp with time zone NOT NULL,
    CONSTRAINT input_forecasts_check CHECK ((valid_at > run_at)),
    CONSTRAINT input_forecasts_check1 CHECK ((available_at >= run_at)),
    CONSTRAINT input_forecasts_kind_check CHECK ((kind = 'forecast'::text))
);


--
-- Name: observations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.observations (
    series_id text NOT NULL,
    valid_at timestamp with time zone NOT NULL,
    value double precision NOT NULL,
    coverage double precision,
    ingested_at timestamp with time zone DEFAULT now() NOT NULL,
    kind text DEFAULT 'observation'::text NOT NULL,
    available_at timestamp with time zone NOT NULL,
    CONSTRAINT observations_check CHECK ((available_at >= valid_at)),
    CONSTRAINT observations_coverage_check CHECK (((coverage > (0)::double precision) AND (coverage <= (1)::double precision))),
    CONSTRAINT observations_kind_check CHECK ((kind = 'observation'::text))
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version character varying NOT NULL
);


--
-- Name: series; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.series (
    id text NOT NULL,
    variable text NOT NULL,
    unit text NOT NULL,
    source text NOT NULL,
    location text NOT NULL,
    aggregation text,
    period interval,
    description text DEFAULT ''::text NOT NULL,
    kind text NOT NULL,
    CONSTRAINT series_kind_check CHECK ((kind = ANY (ARRAY['observation'::text, 'forecast'::text])))
);


--
-- Name: forecast_points forecast_points_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forecast_points
    ADD CONSTRAINT forecast_points_pkey PRIMARY KEY (forecast_id, valid_at);


--
-- Name: forecasts forecasts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forecasts
    ADD CONSTRAINT forecasts_pkey PRIMARY KEY (id);


--
-- Name: forecasts forecasts_station_id_model_issued_at_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forecasts
    ADD CONSTRAINT forecasts_station_id_model_issued_at_key UNIQUE (station_id, model, issued_at);


--
-- Name: input_forecasts input_forecasts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.input_forecasts
    ADD CONSTRAINT input_forecasts_pkey PRIMARY KEY (series_id, run_at, valid_at);


--
-- Name: observations observations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observations
    ADD CONSTRAINT observations_pkey PRIMARY KEY (series_id, valid_at);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: series series_id_kind_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.series
    ADD CONSTRAINT series_id_kind_key UNIQUE (id, kind);


--
-- Name: series series_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.series
    ADD CONSTRAINT series_pkey PRIMARY KEY (id);


--
-- Name: forecast_points forecast_points_forecast_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forecast_points
    ADD CONSTRAINT forecast_points_forecast_id_fkey FOREIGN KEY (forecast_id) REFERENCES public.forecasts(id) ON DELETE CASCADE;


--
-- Name: input_forecasts input_forecasts_series_id_kind_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.input_forecasts
    ADD CONSTRAINT input_forecasts_series_id_kind_fkey FOREIGN KEY (series_id, kind) REFERENCES public.series(id, kind);


--
-- Name: observations observations_series_id_kind_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.observations
    ADD CONSTRAINT observations_series_id_kind_fkey FOREIGN KEY (series_id, kind) REFERENCES public.series(id, kind);


--
-- PostgreSQL database dump complete
--

\unrestrict dbmate


--
-- Dbmate schema migrations
--

INSERT INTO public.schema_migrations (version) VALUES
    ('20261012133232'),
    ('20261012133234'),
    ('20261013150000'),
    ('20261013160000'),
    ('20261013170000'),
    ('20261013180000'),
    ('20261013200000');
