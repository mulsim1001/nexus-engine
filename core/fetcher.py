"""
NEXUS — Data Fetcher
Pengambilan data harga instrumen dengan cascade multi-sumber:

  Sumber 1: Yahoo Finance (yfinance) — gratis, unlimited
  Sumber 2: Twelve Data API         — rescue saat yfinance gagal, hemat kredit

Strategi cascade memastikan kredit Twelve Data hanya terpakai
saat benar-benar dibutuhkan, bukan untuk setiap ticker.
"""

import os
import time
import logging
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from typing import Optional

from config.universe import LQ45_UNIVERSE, BENCHMARK_TICKER
from config.params import (
    DATA_LOOKBACK, DATA_RESOLUTION,
    FETCH_BATCH_SIZE, FETCH_BATCH_PAUSE,
    DATA_MAX_DELAY_MINUTES, MIN_CANDLES_REQUIRED,
    TWELVEDATA_BASE_URL, TWELVEDATA_RESOLUTION, TWELVEDATA_CANDLES,
)

log = logging.getLogger(__name__)

UTC = timezone.utc


# ============================================================
# Sumber 1 — Yahoo Finance (primary)
# ============================================================

def _pull_yfinance(ticker: str) -> Optional[pd.DataFrame]:
    """
    Ambil data OHLCV dari Yahoo Finance.
    Tidak membutuhkan API key. Gratis dan unlimited.
    """
    try:
        import yfinance as yf
        raw = yf.Ticker(ticker).history(period=DATA_LOOKBACK, interval=DATA_RESOLUTION)

        if raw is None or raw.empty:
            log.debug(f"[yfinance] {ticker}: response kosong")
            return None

        raw.index = pd.to_datetime(raw.index)
        df = raw[["Open", "High", "Low", "Close", "Volume"]].dropna()
        return df if not df.empty else None

    except Exception as exc:
        log.warning(f"[yfinance] {ticker}: {exc}")
        return None


# ============================================================
# Sumber 2 — Twelve Data (rescue/fallback)
# ============================================================

def _pull_twelvedata(ticker: str) -> Optional[pd.DataFrame]:
    """
    Ambil data OHLCV dari Twelve Data API.
    Hanya dipanggil saat yfinance gagal — hemat kredit.
    Membutuhkan env var: TWELVEDATA_API_KEY.
    """
    api_key = os.environ.get("TWELVEDATA_API_KEY", "")
    if not api_key:
        log.debug("[TwelveData] API key tidak tersedia — lewati")
        return None

    try:
        symbol = ticker.replace(".JK", "")
        params = {
            "symbol":     symbol,
            "exchange":   "IDX",
            "interval":   TWELVEDATA_RESOLUTION,
            "outputsize": TWELVEDATA_CANDLES,
            "apikey":     api_key,
            "format":     "JSON",
        }

        resp = requests.get(TWELVEDATA_BASE_URL, params=params, timeout=15)
        resp.raise_for_status()
        payload = resp.json()

        if payload.get("status") == "error":
            log.warning(f"[TwelveData] {ticker}: {payload.get('message', 'error tidak diketahui')}")
            return None

        records = payload.get("values", [])
        if not records:
            log.debug(f"[TwelveData] {ticker}: tidak ada data")
            return None

        df = pd.DataFrame(records)
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.set_index("datetime").sort_index()
        df = df.rename(columns={
            "open": "Open", "high": "High",
            "low": "Low",   "close": "Close", "volume": "Volume",
        })
        df = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
        return df

    except Exception as exc:
        log.warning(f"[TwelveData] {ticker}: {exc}")
        return None


# ============================================================
# Validasi Kesegaran Data
# ============================================================

def _is_data_fresh(df: pd.DataFrame, ticker: str) -> bool:
    """
    Tolak data yang terlalu usang.
    Data delayed lebih dari DATA_MAX_DELAY_MINUTES dianggap tidak valid
    karena sinyal yang dihasilkan bisa sudah tidak relevan dengan kondisi pasar terkini.
    """
    if df.empty:
        return False

    last_candle_ts = df.index[-1]
    if last_candle_ts.tzinfo is None:
        last_candle_ts = last_candle_ts.tz_localize("UTC")

    age_minutes = (datetime.now(UTC) - last_candle_ts.to_pydatetime()).total_seconds() / 60

    if age_minutes > DATA_MAX_DELAY_MINUTES:
        log.warning(
            f"[FRESHNESS] {ticker}: candle terakhir {age_minutes:.0f} menit lalu "
            f"(batas {DATA_MAX_DELAY_MINUTES} menit) — data ditolak"
        )
        return False

    return True


# ============================================================
# Cascade Fetcher Utama
# ============================================================

def fetch_instrument(ticker: str) -> Optional[pd.DataFrame]:
    """
    Ambil data satu instrumen dengan cascade multi-sumber.

    Alur:
      1. Coba yfinance → validasi jumlah candle + kesegaran
      2. Jika gagal → coba Twelve Data (1 kredit)
      3. Jika keduanya gagal → return None, ticker diskip

    Return: DataFrame OHLCV yang bersih, atau None.
    """
    # --- Sumber 1: yfinance ---
    df = _pull_yfinance(ticker)
    if df is not None and len(df) >= MIN_CANDLES_REQUIRED:
        if _is_data_fresh(df, ticker):
            log.info(f"[FETCHER] {ticker}: {len(df)} candles via yfinance ✓")
            return df
        log.warning(f"[FETCHER] {ticker}: yfinance data usang — eskalasi ke Twelve Data")
    else:
        log.warning(f"[FETCHER] {ticker}: yfinance gagal atau data tidak cukup — eskalasi ke Twelve Data")

    # --- Sumber 2: Twelve Data ---
    df = _pull_twelvedata(ticker)
    if df is not None and len(df) >= MIN_CANDLES_REQUIRED:
        if _is_data_fresh(df, ticker):
            log.info(f"[FETCHER] {ticker}: {len(df)} candles via Twelve Data ✓")
            return df
        log.warning(f"[FETCHER] {ticker}: Twelve Data juga usang — ticker diskip")
        return None

    log.error(f"[FETCHER] {ticker}: semua sumber gagal — ticker dilewati")
    return None


def fetch_universe() -> dict[str, pd.DataFrame]:
    """
    Ambil data seluruh instrumen dalam LQ45_UNIVERSE secara bertahap (batch).
    Jeda antar batch untuk menghindari rate limit.

    Return: dict { 'BBCA.JK': DataFrame, ... }
    """
    universe = LQ45_UNIVERSE
    total = len(universe)
    batches = [universe[i:i + FETCH_BATCH_SIZE] for i in range(0, total, FETCH_BATCH_SIZE)]
    collected: dict[str, pd.DataFrame] = {}

    log.info(f"[FETCHER] Mulai scan {total} instrumen dalam {len(batches)} batch...")

    for idx, batch in enumerate(batches, start=1):
        log.info(f"[FETCHER] Batch {idx}/{len(batches)}: {batch}")

        for ticker in batch:
            df = fetch_instrument(ticker)
            if df is not None:
                collected[ticker] = df

        if idx < len(batches):
            log.debug(f"[FETCHER] Jeda {FETCH_BATCH_PAUSE}s sebelum batch berikutnya...")
            time.sleep(FETCH_BATCH_PAUSE)

    log.info(f"[FETCHER] Selesai. Berhasil: {len(collected)}/{total} instrumen.")
    return collected


def fetch_benchmark() -> Optional[pd.DataFrame]:
    """
    Ambil data IHSG sebagai referensi kondisi makro pasar.
    Hanya dari yfinance — benchmark tidak butuh fallback premium.
    """
    log.info(f"[FETCHER] Mengambil data benchmark ({BENCHMARK_TICKER})...")
    df = _pull_yfinance(BENCHMARK_TICKER)
    if df is not None:
        log.info(f"[FETCHER] Benchmark: {len(df)} candles ✓")
    else:
        log.warning("[FETCHER] Data benchmark tidak tersedia — konteks makro dinonaktifkan")
    return df


def get_last_price(df: pd.DataFrame) -> float:
    """Ambil harga penutupan candle terakhir."""
    return float(df["Close"].iloc[-1])
