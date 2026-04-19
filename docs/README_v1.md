# NEXUS Market Intelligence Engine
## Technical Documentation — Version 1.0.0

**Status:** Production Ready  
**Last Updated:** April 2026  
**Runtime:** Python 3.11  
**Deployment:** GitHub Actions + Supabase  

---

## Table of Contents

1. [Overview](#1-overview)
2. [System Requirements](#2-system-requirements)
3. [Installation](#3-installation)
4. [Configuration](#4-configuration)
5. [Database Setup](#5-database-setup)
6. [Module Reference](#6-module-reference)
7. [Scoring Engine Specification](#7-scoring-engine-specification)
8. [Filter Pipeline](#8-filter-pipeline)
9. [Data Source Strategy](#9-data-source-strategy)
10. [Deployment](#10-deployment)
11. [Error Handling & Fail-Safe Behavior](#11-error-handling--fail-safe-behavior)
12. [Monitoring](#12-monitoring)
13. [Limitations & Disclaimer](#13-limitations--disclaimer)

---

## 1. Overview

NEXUS is an automated technical analysis system for Indonesian Stock Exchange (IDX) instruments. It operates on a 10-minute polling cycle during active trading sessions and delivers structured alerts via Telegram.

The system implements a **5-layer confluence scoring engine**, where a signal is dispatched only when multiple independent analytical layers reach consensus. No single layer can override the combined judgment of others.

**Design principles:**
- Fail-safe over fail-open: when external dependencies are unavailable, the system halts rather than proceeding with degraded guarantees
- Multi-source resilience: data acquisition cascades across providers, minimizing single-point-of-failure risk
- Minimal false positives: dual-scan confirmation and per-ticker cooldown suppress noise

---

## 2. System Requirements

| Requirement | Value |
|---|---|
| Python | 3.11+ |
| GitHub repository visibility | Public (for unlimited Actions minutes) |
| Supabase project | Free tier sufficient |
| Telegram Bot | Required |
| Twelve Data API key | Optional (fallback only) |

**Python dependencies:**

```
yfinance==0.2.51
pandas==2.2.3
numpy==2.2.3
requests==2.32.3
```

---

## 3. Installation

### 3.1 Repository Setup

```bash
# Clone or initialize repository
git clone <your-repo-url>
cd nexus-engine

# Install dependencies
pip install -r requirements.txt

# Verify structure
python -c "from core.engine import evaluate; print('OK')"
```

### 3.2 Manual Execution (Testing)

```bash
# Set required environment variables
export TELEGRAM_BOT_TOKEN="your_token"
export TELEGRAM_CHAT_ID="your_chat_id"
export SUPABASE_URL="https://your-project.supabase.co"
export SUPABASE_KEY="your_service_role_key"
export TWELVEDATA_API_KEY="your_key"   # optional

python run.py
```

---

## 4. Configuration

All system parameters are centralized in `config/params.py`. No configuration is scattered across modules.

### 4.1 Core Parameters

| Parameter | Default | Description |
|---|---|---|
| `SESSION_OPEN_HOUR` | `9` | Market open hour (WIB/UTC+7) |
| `SESSION_CLOSE_HOUR` | `15` | Market close hour |
| `SESSION_CLOSE_MINUTE` | `50` | Buffer before official 16:00 close |
| `POLL_INTERVAL_MINUTES` | `10` | Polling frequency (used for documentation; actual scheduling in pulse.yml) |

### 4.2 Scoring Layer Weights

| Layer | Weight |
|---|---|
| PULSE (Trend) | 30% |
| RADAR (Momentum) | 25% |
| FLOW (Volume) | 25% |
| FORMATION (Pattern) | 10% |
| MACRO (Benchmark) | 10% |
| **Total** | **100%** |

### 4.3 Signal Thresholds

| Parameter | Default | Description |
|---|---|---|
| `CONVICTION_HIGH` | `80` | Minimum rating for STRONG signal |
| `CONVICTION_MODERATE` | `65` | Minimum rating for regular signal |
| `COOLDOWN_PER_TICKER` | `60` | Minutes between repeated alerts per ticker |
| `MAX_DAILY_ALERTS` | `8` | Maximum alerts dispatched per calendar day |
| `CONFIRM_ROUNDS` | `2` | Consecutive scans required before dispatch |

### 4.4 Data Acquisition

| Parameter | Default | Description |
|---|---|---|
| `DATA_LOOKBACK` | `"5d"` | Historical range requested from data source |
| `DATA_RESOLUTION` | `"5m"` | Candle interval |
| `DATA_MAX_DELAY_MINUTES` | `30` | Maximum acceptable data age |
| `MIN_CANDLES_REQUIRED` | `55` | Minimum candles for valid analysis |
| `FETCH_BATCH_SIZE` | `10` | Instruments per batch request |
| `FETCH_BATCH_PAUSE` | `2` | Seconds between batches |

---

## 5. Database Setup

Execute `supabase_setup.sql` once via the Supabase SQL Editor.

This creates two tables:

**`alert_log`** — Permanent record of all dispatched alerts. Used for:
- Cooldown enforcement
- Daily alert count
- Session summary generation

**`pending_alerts`** — Temporary buffer for signals awaiting second-scan confirmation. Records older than 30 minutes are purged at the start of each cycle.

### Important: Use Service Role Key

The `SUPABASE_KEY` secret must be the **Service Role Key** (not the anon key). The anon key has restricted INSERT/DELETE permissions that will cause storage operations to fail silently.

---

## 6. Module Reference

### `run.py` — Orchestrator

Entry point. Manages the execution lifecycle:
1. Session boundary check (day of week + time)
2. Ledger connectivity verification (fail-safe gate)
3. Stale pending alert cleanup
4. Data acquisition (benchmark + universe)
5. Per-instrument evaluation loop
6. Alert filter pipeline (cooldown → daily limit → confirmation)
7. Alert dispatch + ledger recording
8. Session summary (near close)

**Key behavior:** If `count_alerts_today()` returns `None` (Supabase unreachable), the orchestrator calls `sys.exit(1)`. This causes GitHub Actions to mark the run as failed, which is intentional — it surfaces the infrastructure issue rather than silently proceeding.

---

### `core/fetcher.py` — Data Fetcher

Implements a two-source cascade for OHLCV data acquisition.

**Public API:**

| Function | Parameters | Returns |
|---|---|---|
| `fetch_universe()` | — | `dict[str, DataFrame]` |
| `fetch_benchmark()` | — | `Optional[DataFrame]` |
| `fetch_instrument(ticker)` | `str` | `Optional[DataFrame]` |
| `get_last_price(df)` | `DataFrame` | `float` |

**Cascade behavior:**
1. Attempt yfinance; validate candle count and data freshness
2. On failure: attempt Twelve Data (1 credit consumed)
3. On double failure: return `None`; ticker is excluded from this cycle

---

### `core/engine.py` — Scoring Engine

Implements the 5-layer confluence evaluation.

**Public API:**

| Function | Parameters | Returns |
|---|---|---|
| `evaluate(ticker, df, benchmark_df)` | `str, DataFrame, Optional[DataFrame]` | `Optional[AlertPacket]` |

**`AlertPacket` fields:**

| Field | Type | Description |
|---|---|---|
| `ticker` | `str` | Instrument code |
| `rating` | `float` | Aggregate score 0–100 |
| `verdict` | `str` | `STRONG_LONG / LONG / HOLD / SHORT / STRONG_SHORT` |
| `last_price` | `float` | Last close price |
| `upside_level` | `float` | Calculated target price |
| `guard_level` | `float` | Calculated stop level |
| `conviction` | `str` | `STRONG / MODERATE / WEAK` |
| `pulse_rating` | `float` | Layer 1 sub-score (0–100) |
| `radar_rating` | `float` | Layer 2 sub-score (0–100) |
| `flow_rating` | `float` | Layer 3 sub-score (0–100) |
| `formation_rating` | `float` | Layer 4 sub-score (0–100) |
| `macro_rating` | `float` | Layer 5 sub-score (0–100) |
| `notes` | `list[str]` | Ordered analysis notes |
| `rsi_value` | `float` | Raw RSI reading |
| `macd_delta` | `float` | MACD histogram value |
| `flow_ratio` | `float` | Volume ratio vs 20-day average |
| `adx_value` | `float` | ADX trend strength reading |

---

### `core/dispatcher.py` — Alert Dispatcher

Handles Telegram message formatting and delivery.

**Public API:**

| Function | Parameters | Returns |
|---|---|---|
| `dispatch_alert(packet)` | `AlertPacket` | `bool` |
| `dispatch_session_summary(alerts, scanned)` | `list[dict], int` | `bool` |
| `inter_message_pause()` | — | `None` |

**Retry behavior:** Up to 3 attempts with exponential backoff (2s, 4s, 6s). HTTP 429 responses read the `Retry-After` header for precise wait duration.

---

### `core/ledger.py` — State Manager

Manages persistent state via Supabase REST API.

**Public API:**

| Function | Returns | Fail-safe behavior |
|---|---|---|
| `is_on_cooldown(ticker, verdict, minutes)` | `Optional[bool]` | Returns `None` on error |
| `count_alerts_today()` | `Optional[int]` | Returns `None` on error |
| `record_alert(ticker, verdict, rating, price)` | `bool` | Returns `False` on error |
| `get_pending_count(ticker, verdict)` | `int` | Returns `0` on error |
| `register_pending(ticker, verdict, rating)` | `bool` | Returns `False` on error |
| `purge_expired_pending(max_age_minutes)` | `None` | Logs error, continues |
| `get_all_alerts_today()` | `list[dict]` | Returns `[]` on error |

**Critical distinction:** `is_on_cooldown()` and `count_alerts_today()` return `None` (not `False`/`0`) on connectivity failure. The orchestrator treats `None` as a hard stop, preventing dispatch without cooldown verification.

---

## 7. Scoring Engine Specification

### 7.1 PULSE Layer — Trend Detection

**Formula:**
```
votes = 0
votes += 1 if price > EMA(20)
votes += 1 if EMA(20) > EMA(50)
votes += 1 if EMA(50) > EMA(100)
votes -= 1 per failed condition

if ADX < 15: votes *= 0.4  (sideways market penalty)

normalized = (votes + 3) / 6
```

Output range: `[0.0, 1.0]` (symmetric around 0.5)

### 7.2 RADAR Layer — Oscillator Consensus

Minimum 3/4 oscillators must agree for a non-neutral score.

**RSI:** Bullish below 30, Bearish above 70  
**Stochastic:** Bullish when %K < 20 and crossing up; Bearish when %K > 80 and crossing down  
**MACD:** Full vote (1.0) on crossover, partial vote (0.5) on histogram position  
**CCI:** Bullish below -100, Bearish above +100

### 7.3 FLOW Layer — Volume Analysis

Unique among layers: can produce scores below 0.5 (bearish volume distribution).

Components:
- Volume surge bonus: +0.25 (≥2.5x avg) or +0.12 (≥1.5x avg)
- Volume deficit penalty: -0.10 (<0.7x avg)
- OBV trend: ±0.12
- MFI extremes: ±0.12

### 7.4 FORMATION Layer — Pattern Recognition

Binary output: 0.8 (bullish patterns dominant), 0.2 (bearish dominant), 0.5 (neutral/mixed)

Patterns: Bollinger Band touch, Hammer, Shooting Star, Bullish Engulfing, Bearish Engulfing

### 7.5 MACRO Layer — Benchmark Context

IHSG-based market regime classification:

| IHSG Change | Score | Regime |
|---|---|---|
| ≤ −2% | 0.10 | Full defensive |
| −2% to −1% | 0.30 | Cautious |
| −1% to +1% | 0.55 | Stable |
| ≥ +1% | 0.80 | Positive |

---

## 8. Filter Pipeline

Each candidate alert passes through the following filters in order:

```
[1] verdict == HOLD → SKIP
[2] is_on_cooldown() == True → SKIP
[3] is_on_cooldown() == None → SKIP (Supabase unreachable)
[4] alerts_today + dispatched >= MAX_DAILY_ALERTS → SKIP
[5] pending_count < CONFIRM_ROUNDS - 1 → register pending, SKIP
[6] All filters passed → DISPATCH
```

---

## 9. Data Source Strategy

### 9.1 Source Hierarchy

| Priority | Source | Cost | Rate Limit | Format |
|---|---|---|---|---|
| 1 | Yahoo Finance (yfinance) | Free | Unofficial | `BBCA.JK` |
| 2 | Twelve Data API | Free tier: 800 credits/day | 8 req/min | `BBCA` + `exchange=IDX` |

### 9.2 Freshness Validation

Data is considered stale if the most recent candle timestamp is more than `DATA_MAX_DELAY_MINUTES` (30) minutes old relative to UTC now. Stale data is rejected regardless of source, protecting the scoring engine from operating on outdated market conditions.

---

## 10. Deployment

### 10.1 GitHub Secrets

| Secret | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Yes | From @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | Target group/channel ID |
| `SUPABASE_URL` | Yes | Supabase project URL |
| `SUPABASE_KEY` | Yes | Service Role Key (not anon) |
| `TWELVEDATA_API_KEY` | No | Twelve Data API key |

### 10.2 Schedule

The `pulse.yml` workflow triggers every 10 minutes on weekdays between 02:00–08:59 UTC (09:00–15:59 WIB). `run.py` performs its own session boundary check as a secondary guard.

### 10.3 Concurrency

The workflow uses `concurrency.group: nexus-market-pulse` with `cancel-in-progress: false`. If a cycle is still running when the next trigger fires, the new instance is cancelled (not the running one), preventing race conditions on Supabase state.

---

## 11. Error Handling & Fail-Safe Behavior

| Failure Condition | Behavior |
|---|---|
| Supabase unreachable at startup | `sys.exit(1)` — full cycle abort |
| Supabase unreachable per-ticker | Skip ticker, log error |
| yfinance failure | Escalate to Twelve Data |
| Twelve Data failure | Skip ticker |
| Data stale (> 30 min) | Skip ticker |
| Telegram send failure | Retry 3x with backoff, log on final failure |

---

## 12. Monitoring

**GitHub Actions UI:** Each run's log output is visible in the Actions tab. Failed runs (exit code 1) are marked with a red indicator.

**Log artifacts:** On failure, logs are uploaded as GitHub Actions artifacts (retention: 5 days).

**Supabase dashboard:** `alert_log` table provides a real-time ledger of all dispatched alerts for manual review.

---

## 13. Limitations & Disclaimer

1. **Data delay:** Yahoo Finance data for IDX instruments typically has a 15–20 minute delay. The system is therefore a **near-real-time** system, not true real-time.

2. **No backtest validation:** Version 1.0 does not include historical performance metrics. Signal accuracy is unverified against historical data.

3. **Not investment advice:** This system is an algorithmic technical analysis tool. It does not account for fundamental analysis, macroeconomic events, company announcements, or regulatory changes. All outputs should be treated as one input among many in a broader investment decision process.

4. **Free tier limits:** Supabase free tier databases are paused after 1 week of inactivity. Ensure the system runs regularly or configure a keep-alive mechanism.
