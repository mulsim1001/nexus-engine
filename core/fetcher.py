"""
NEXUS — Data Fetcher
Pengambilan data harga instrumen dengan cascade multi-sumber:

  Sumber 1: Yahoo Finance (yfinance) — gratis, unlimited
  Sumber 2: Twelve Data API         — rescue saat yfinance gagal, hemat kredit

Strategi cascade memastikan kredit Twelve Data hanya terpakai
saat benar-benar dibutuhkan, bukan untuk setiap ticker.

Optimasi reliability:
  - Batch download multi-ticker dalam 1 request (turunkan jumlah hit ke Yahoo)
  - Browser impersonation via curl_cffi (hindari deteksi bot)
  - Retry dengan backoff (atasi rate-limit sesaat)
  - Freshness check IDX-aware (akomodasi jam istirahat 11:30-13:30 WIB)
  - Cache benchmark dalam-proses
"""

import os
import time
import random
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
    FETCH_RETRY_COUNT, FETCH_RETRY_BASE_DELAY,
    BENCHMARK_CACHE_MINUTES,
    TWELVEDATA_BASE_URL, TWELVEDATA_RESOLUTION, TWELVEDATA_CANDLES,
    SESSION_OPEN_HOUR, SESSION_OPEN_MINUTE,
    SESSION_CLOSE_HOUR, SESSION_CLOSE_MINUTE,
)

log = logging.getLogger(__name__)

UTC = timezone.utc
WIB = timezone(timedelta(hours=7))

# Cache benchmark dalam-proses (dict supaya bisa direset)
_benchmark_cache: dict = {"df": None, "ts": None}


# ============================================================
# Session HTTP dengan browser impersonation
# ============================================================

def _build_session():
    """
    Bangun session curl_cffi yang menyamar sebagai Chrome.
    Fallback ke requests biasa kalau curl_cffi tidak tersedia.
    """
    try:
        from curl_cffi import requests as curl_requests
        return curl_requests.Session(impersonate="chrome")
    except Exception as exc:
        log.warning(f"[FETCHER] curl_cffi tidak tersedia ({exc}) — fallback ke session biasa")
        return None


_YF_SESSION = _build_session()


# ============================================================
# Helper waktu & sesi IDX
# ============================================================

def _is_idx_actively_trading(now: Optional[datetime] = None) -> bool:
    """
    True hanya saat bursa BENAR-BENAR aktif memperdagangkan
    (di luar jam istirahat 11:30-13:30 WIB).
    Di luar window aktif, freshness check tidak relevan — candle terakhir
    memang akan tampak "tua" dan itu wajar.
    """
    now = now or datetime.now(WIB)

    if now.weekday() >= 5:
        return False

    t = now.time()
    sesi1_start = datetime.strptime("09:00", "%H:%M").time()
    sesi1_end   = datetime.strptime("11:30", "%H:%M").time()
    sesi2_start = datetime.strptime("13:30", "%H:%M").time()
    sesi2_end   = datetime.strptime(
        f"{SESSION_CLOSE_HOUR:02d}:{SESSION_CLOSE_MINUTE:02d}", "%H:%M"
    ).time()

    in_sesi1 = sesi1_start <= t <= sesi1_end
    in_sesi2 = sesi2_start <= t <= sesi2_end
    return in_sesi1 or in_sesi2


# ============================================================
# Sumber 1 — Yahoo Finance (primary, batch download)
# ============================================================

def _yf_download_batch(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """
    Ambil banyak ticker sekaligus dalam 1 request ke Yahoo.
    Jauh lebih ramah rate-limit dibanding loop per ticker.
    Return dict {ticker: DataFrame}. Ticker yang gagal tidak masuk dict.
    """
    import yfinance as yf

    if not tickers:
        return {}

    last_exc = None
    for attempt in range(1, FETCH_RETRY_COUNT + 1):
        try:
            kwargs = dict(
                tickers=" ".join(tickers),
                period=DATA_LOOKBACK,
                interval=DATA_RESOLUTION,
                group_by="ticker",
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            if _YF_SESSION is not None:
                kwargs["session"] = _YF_SESSION

            raw = yf.download(**kwargs)

            if raw is None or raw.empty:
                raise RuntimeError("response kosong")

            results: dict[str, pd.DataFrame] = {}

            # Kalau hanya 1 ticker, yfinance tidak bikin MultiIndex
            if len(tickers) == 1:
                t = tickers[0]
                df = raw[["Open", "High", "Low", "Close", "Volume"]].dropna()
                if not df.empty:
                    df.index = pd.to_datetime(df.index)
                    results[t] = df
                return results

            # Multi-ticker → kolom bertingkat (ticker, field)
            for t in tickers:
                if t not in raw.columns.get_level_values(0):
                    continue
                sub = raw[t][["Open", "High", "Low", "Close", "Volume"]].dropna()
                if sub.empty:
                    continue
                sub.index = pd.to_datetime(sub.index)
                results[t] = sub

            return results

        except Exception as exc:
            last_exc = exc
            if attempt < FETCH_RETRY_COUNT:
                delay = FETCH_RETRY_BASE_DELAY * attempt + random.random()
                log.warning(
                    f"[yfinance] batch gagal (attempt {attempt}/{FETCH_RETRY_COUNT}): {exc} "
                    f"— retry dalam {delay:.1f}s"
                )
                time.sleep(delay)

    log.warning(f"[yfinance] batch gagal total setelah {FETCH_RETRY_COUNT} percobaan: {last_exc}")
    return {}


def _pull_yfinance(ticker: str) -> Optional[pd.DataFrame]:
    """
    Ambil 1 ticker dari Yahoo (dipakai untuk fallback per-ticker dan benchmark).
    """
    results = _yf_download_batch([ticker])
    return results.get(ticker)


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
# Validasi Kesegaran Data (IDX-aware)
# ============================================================

def _is_data_fresh(df: pd.DataFrame, ticker: str) -> bool:
    """
    Tolak data usang HANYA saat bursa sedang aktif memperdagangkan.
    Saat istirahat (11:30-13:30 WIB) atau di luar sesi, candle terakhir
    memang akan tampak tua — itu wajar dan bukan masalah.
    """
    if df.empty:
        return False

    # Di luar window aktif → terima apa adanya
    if not _is_idx_actively_trading():
        return True

    last_candle_ts = df.index[-1]
    if last_candle_ts.tzinfo is None:
        last_candle_ts = last_candle_ts.tz_localize("UTC")

    age_minutes = (datetime.now(UTC) - last_candle_ts.to_pydatetime()).total_seconds() / 60

    if age_minutes > DATA_MAX_DELAY_MINUTES:
        log.warning(
            f"[FRESHNESS] {ticker}: candle terakhir {age_minutes:.0f} menit lalu "
            f"(batas {DATA_MAX_DELAY_MINUTES} menit, bursa aktif) — data ditolak"
        )
        return False

    return True


# ============================================================
# Cascade Fetcher Per-Ticker (untuk fallback & benchmark)
# ============================================================

def fetch_instrument(ticker: str) -> Optional[pd.DataFrame]:
    """
    Ambil data satu instrumen dengan cascade multi-sumber.

    Alur:
      1. Coba yfinance → validasi jumlah candle + kesegaran
      2. Jika gagal → coba Twelve Data (1 kredit)
      3. Jika keduanya gagal → return None, ticker diskip
    """
    df = _pull_yfinance(ticker)
    if df is not None and len(df) >= MIN_CANDLES_REQUIRED:
        if _is_data_fresh(df, ticker):
            log.info(f"[FETCHER] {ticker}: {len(df)} candles via yfinance ✓")
            return df
        log.warning(f"[FETCHER] {ticker}: yfinance data usang — eskalasi ke Twelve Data")
    else:
        log.warning(f"[FETCHER] {ticker}: yfinance gagal atau data tidak cukup — eskalasi ke Twelve Data")

    df = _pull_twelvedata(ticker)
    if df is not None and len(df) >= MIN_CANDLES_REQUIRED:
        if _is_data_fresh(df, ticker):
            log.info(f"[FETCHER] {ticker}: {len(df)} candles via Twelve Data ✓")
            return df
        log.warning(f"[FETCHER] {ticker}: Twelve Data juga usang — ticker diskip")
        return None

    log.error(f"[FETCHER] {ticker}: semua sumber gagal — ticker dilewati")
    return None


# ============================================================
# Fetch Universe (BATCH MODE — 1 request per batch)
# ============================================================

def fetch_universe() -> dict[str, pd.DataFrame]:
    """
    Ambil data seluruh instrumen LQ45 dalam mode BATCH.
    Tiap batch = 1 request multi-ticker ke Yahoo (bukan loop per ticker).
    Ticker yang tidak tertangkap atau usang dieskalasi ke Twelve Data.
    """
    universe = LQ45_UNIVERSE
    total = len(universe)
    batches = [universe[i:i + FETCH_BATCH_SIZE] for i in range(0, total, FETCH_BATCH_SIZE)]
    collected: dict[str, pd.DataFrame] = {}

    log.info(f"[FETCHER] Mulai scan {total} instrumen dalam {len(batches)} batch (mode multi-ticker)...")

    for idx, batch in enumerate(batches, start=1):
        log.info(f"[FETCHER] Batch {idx}/{len(batches)}: {batch}")

        # 1 request untuk seluruh batch
        batch_results = _yf_download_batch(batch)

        # Klasifikasikan: yang lolos langsung simpan, yang tidak → fallback per-ticker
        need_fallback: list[str] = []
        for ticker in batch:
            df = batch_results.get(ticker)
            if df is None or len(df) < MIN_CANDLES_REQUIRED:
                need_fallback.append(ticker)
                continue
            if not _is_data_fresh(df, ticker):
                need_fallback.append(ticker)
                continue
            collected[ticker] = df
            log.info(f"[FETCHER] {ticker}: {len(df)} candles via yfinance batch ✓")

        # Fallback per-ticker untuk yang gagal di batch
        for ticker in need_fallback:
            log.warning(f"[FETCHER] {ticker}: tidak lolos batch — coba per-ticker / Twelve Data")
            df = fetch_instrument(ticker)
            if df is not None:
                collected[ticker] = df

        if idx < len(batches):
            time.sleep(FETCH_BATCH_PAUSE)

    log.info(f"[FETCHER] Selesai. Berhasil: {len(collected)}/{total} instrumen.")
    return collected


# ============================================================
# Fetch Benchmark (dengan cache dalam-proses)
# ============================================================

def fetch_benchmark() -> Optional[pd.DataFrame]:
    """
    Ambil data IHSG sebagai referensi kondisi makro pasar.
    Hasil di-cache selama BENCHMARK_CACHE_MINUTES menit.
    """
    now = datetime.now(UTC)
    cached_df = _benchmark_cache.get("df")
    cached_ts = _benchmark_cache.get("ts")

    if cached_df is not None and cached_ts is not None:
        age = (now - cached_ts).total_seconds() / 60
        if age < BENCHMARK_CACHE_MINUTES:
            log.info(f"[FETCHER] Benchmark dari cache (umur {age:.1f} menit)")
            return cached_df

    log.info(f"[FETCHER] Mengambil data benchmark ({BENCHMARK_TICKER})...")
    df = _pull_yfinance(BENCHMARK_TICKER)
    if df is not None:
        log.info(f"[FETCHER] Benchmark: {len(df)} candles ✓")
        _benchmark_cache["df"] = df
        _benchmark_cache["ts"] = now
    else:
        log.warning("[FETCHER] Data benchmark tidak tersedia — konteks makro dinonaktifkan")
    return df


def get_last_price(df: pd.DataFrame) -> float:
    """Ambil harga penutupan candle terakhir."""
    return float(df["Close"].iloc[-1])
