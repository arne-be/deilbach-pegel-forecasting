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
    level_m double precision NOT NULL
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
-- Name: raw_observations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.raw_observations (
    station_id text NOT NULL,
    observed_at timestamp with time zone NOT NULL,
    level_m double precision NOT NULL,
    source text NOT NULL,
    ingested_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version character varying NOT NULL
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
-- Name: raw_observations raw_observations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.raw_observations
    ADD CONSTRAINT raw_observations_pkey PRIMARY KEY (station_id, observed_at);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: forecast_points forecast_points_forecast_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.forecast_points
    ADD CONSTRAINT forecast_points_forecast_id_fkey FOREIGN KEY (forecast_id) REFERENCES public.forecasts(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict dbmate


--
-- Dbmate schema migrations
--

INSERT INTO public.schema_migrations (version) VALUES
    ('20261012133232'),
    ('20261012133234');
