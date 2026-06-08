# Broaden Futures Anomaly Alerts

## Problem

The previous noise reduction narrowed source-side webhook forwarding to price velocity only. That misses futures-market drivers the user cares about: volume, open interest, and funding rate. Kairos should forward any meaningful anomaly in futures-market conditions to Hermes for analysis.

## Requirements

- Keep source-side thresholds and cooldowns so raw noise does not flood Hermes.
- Forward any configured futures anomaly type to Hermes when it crosses threshold:
  - price velocity
  - volume spike
  - open interest change
  - funding rate anomaly
- Add open-interest and funding-rate polling because these metrics are not delivered through the current ticker WebSocket detector path.
- Include enough detail in the webhook condition string for Hermes to understand why the event fired.
- Keep OKX Top 30 on `ccs`.
- Deploy updated config on `ccs` so volume, open-interest, and funding anomalies are enabled.

## Acceptance Criteria

- Unit tests cover open-interest and funding anomaly detection.
- DataManager registers and stops the futures metrics polling loop cleanly.
- Alert policy allows all four event types by default.
- Related tests and ruff pass locally and on `ccs`.
- `ccs` service is active after deployment and logs show Top 30 plus futures metrics detector enabled.
