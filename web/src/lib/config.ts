// The site's slice of config/pegel.json, read at build time. Nothing else hard-codes these.
import {
  categories as configCategories,
  freshness as configFreshness,
  forecast,
  site,
} from "../../../config/pegel.json";

export interface Category {
  number: number;
  name: string;
  /** The category applies when the level is strictly above this; null for the first one. */
  above_cm: number | null;
  description: string;
  actions: string;
}

export interface SupportTier {
  id: string;
  name: string;
  eur_per_month: number;
  description: string;
  /** Recurring Stripe Payment Link; null until it exists. */
  url: string | null;
}

export interface SupportAmount {
  eur: number;
  /** Fixed-price Stripe Payment Link; null until it exists. */
  url: string | null;
}

export interface Support {
  tiers: SupportTier[];
  one_off: SupportAmount[];
  /** Stripe Payment Link where the visitor picks the amount. */
  custom_url: string | null;
  /** Stripe customer portal where subscribers change or cancel; optional. */
  manage_url: string | null;
  /** The support prompt shows from this visit on; null turns it off. */
  prompt_after_visits: number | null;
}

export interface Freshness {
  observation_max_age_minutes: number;
  forecast_max_age_minutes: number;
}

/** Ascending; the first has `above_cm: null` (validated in src/pegel/config.py). */
export const categories: readonly Category[] = configCategories;
export const freshness: Freshness = configFreshness;
/** Hours the forecast reaches ahead. */
export const horizonHours: number = forecast.horizon_hours;
/** Hours of measured levels the chart shows before the forecast. */
export const historyHours: number = site.history_hours;
/** Top of the chart and scene scale in cm; it grows only if a value goes higher. */
export const scaleTopCm: number = site.scale_top_cm;
/** Monthly tiers and one-off amounts, each a Stripe Payment Link (validated in src/pegel/config.py). */
export const support: Support = site.support;
/** The page offers support only when every link is set, so no button ever leads nowhere. */
export const supportReady: boolean =
  support.custom_url !== null &&
  [...support.tiers, ...support.one_off].every((item) => item.url !== null);
