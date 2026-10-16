// The site's slice of config/pegel.json, read at build time. Nothing else hard-codes these.
import {
  categories as configCategories,
  freshness as configFreshness,
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

export interface Freshness {
  observation_max_age_minutes: number;
  forecast_max_age_minutes: number;
}

/** Ascending; the first has `above_cm: null` (validated in src/pegel/config.py). */
export const categories: readonly Category[] = configCategories;
export const freshness: Freshness = configFreshness;
/** Hours of measured levels the chart shows before the forecast. */
export const historyHours: number = site.history_hours;
/** Top of the chart and scene scale in cm; it grows only if a value goes higher. */
export const scaleTopCm: number = site.scale_top_cm;
