---
description: Standards for data pipelines, jobs and forecasting models
---

# Data Pipelines and ML

## Pipelines and jobs
- **Idempotent jobs.** Rerunning a job for the same time window gives the same result and no duplicates (upsert on natural keys such as station + timestamp).
- **Backfill-friendly.** Every job takes its time window as a parameter, so past periods can be reprocessed.
- Keep raw data as received; derive cleaned data from it so cleaning can be redone.
- Check schemas, units, value ranges and timestamps when data enters the system.
- External calls use timeouts and retries with backoff. After retries fail, fail visibly instead of producing partial output.
- Schema changes go through versioned migrations, never by hand.

## Models
- Build and beat a simple baseline (e.g. persistence) first; report every model against it.
- Use only inputs available at issue time — rain *forecasts* as issued, not observed future rain.
- Split train/test by time, never randomly.
- Report errors per lead time and separately for high water (rising limbs, peak height and timing), not just overall RMSE.
- Uncertainty ranges come from empirical errors of past forecasts, per lead time.
- Version every trained model with its data window, config, code commit and metrics.
- Weekly retraining only promotes a new model if it beats the current one on the same evaluation. Keep the previous model so rollback is a config change.
- Share feature code between training and inference so they cannot drift apart.
- Seed randomness in training.
- Notebooks are for exploration only; move anything reused into tested modules.
