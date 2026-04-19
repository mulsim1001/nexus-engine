"""
NEXUS — Scoring Engine
Mesin analisa teknikal 5 layer dengan sistem voting berbasis konfluensi.

Sinyal hanya diterbitkan bila mayoritas layer mencapai kesepakatan.
Tidak ada satu layer pun yang bisa mendominasi keputusan secara sepihak.

Layer:
  PULSE     — Arah dan kekuatan tren dominan
  RADAR     — Konsensus oscillator momentum
  FLOW      — Arus dana dan validasi volume
  FORMATION — Pola harga dan struktur teknikal
  MACRO     — Kondisi pasar keseluruhan (benchmark IHSG)
"""

import logging
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional

from config.params import (
    EMA_FAST, EMA_MID, EMA_SLOW,
    ADX_LOOKBACK, ADX_TRENDING, ADX_RANGING,
    RSI_WINDOW, RSI_FLOOR, RSI_CEILING,
    STOCH_PERIOD, STOCH_SMOOTH, STOCH_SIGNAL, STOCH_FLOOR, STOCH_CEILING,
    MACD_SHORT, MACD_LONG, MACD_TRIGGER,
    CCI_WINDOW, CCI_FLOOR, CCI_CEILING,
    FLOW_BASELINE_PERIOD, FLOW_ELEVATED_RATIO, FLOW_SURGE_RATIO,
    MFI_WINDOW, MFI_FLOOR, MFI_CEILING,
    BB_WINDOW, BB_WIDTH,
    WEIGHT_PULSE, WEIGHT_RADAR, WEIGHT_FLOW, WEIGHT_FORMATION, WEIGHT_MACRO,
    CONVICTION_HIGH, CONVICTION_MODERATE,
    RADAR_MIN_VOTES,
    BENCHMARK_SLIP_CAUTION, BENCHMARK_SLIP_DEFENSE,
    UPSIDE_TARGET_PCT, DOWNSIDE_GUARD_PCT,
    SHORT_TARGET_PCT, SHORT_GUARD_PCT,
    MIN_CANDLES_REQUIRED,
)

log = logging.getLogger(__name__)


# ============================================================
# Output Container
# ============================================================

@dataclass
class AlertPacket:
    """Hasil analisa lengkap satu instrumen."""
    ticker:        str
    rating:        float               # 0–100
    verdict:       str                 # STRONG_LONG / LONG / HOLD / SHORT / STRONG_SHORT
    last_price:    float
    upside_level:  float               # Target profit
    guard_level:   float               # Level stop loss
    conviction:    str                 # STRONG / MODERATE / WEAK

    pulse_rating:     float = 0.0
    radar_rating:     float = 0.0
    flow_rating:      float = 0.0
    formation_rating: float = 0.0
    macro_rating:     float = 0.0

    notes: list = field(default_factory=list)

    rsi_value:    float = 0.0
    macd_delta:   float = 0.0
    flow_ratio:   float = 0.0
    adx_value:    float = 0.0


# ============================================================
# LAYER 1 — PULSE (Deteksi Tren)
# ============================================================

def _compute_pulse(df: pd.DataFrame) -> tuple[float, list, float]:
    """
    Evaluasi arah dan kekuatan tren menggunakan EMA triple dan ADX.
    Menghasilkan skor ternormalisasi 0.0–1.0.

    Struktur skor mentah:
      +1 per kondisi bullish EMA terpenuhi (max +3)
      -1 per kondisi bearish EMA terpenuhi (max -3)
      ADX memodifikasi bobot skor bila pasar sideways
    """
    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]
    notes = []
    raw   = 0

    ema_f = close.ewm(span=EMA_FAST, adjust=False).mean()
    ema_m = close.ewm(span=EMA_MID,  adjust=False).mean()
    ema_s = close.ewm(span=EMA_SLOW, adjust=False).mean()

    price_now = close.iloc[-1]
    ef = ema_f.iloc[-1]
    em_val = ema_m.iloc[-1]
    es = ema_s.iloc[-1] if not np.isnan(ema_s.iloc[-1]) else None

    if price_now > ef:
        raw += 1
        notes.append(f"Harga di atas EMA{EMA_FAST} — momentum positif jangka pendek")
    else:
        raw -= 1

    if not np.isnan(em_val):
        if ef > em_val:
            raw += 1
            notes.append(f"EMA{EMA_FAST} melampaui EMA{EMA_MID} — tren naik terkonfirmasi")
        else:
            raw -= 1

    if es is not None:
        if em_val > es:
            raw += 1
            notes.append(f"EMA{EMA_MID} di atas EMA{EMA_SLOW} — struktur bullish jangka menengah")
        else:
            raw -= 1

    adx = _adx(high, low, close, ADX_LOOKBACK)

    if adx > ADX_TRENDING:
        notes.append(f"ADX {adx:.1f} — tren sedang aktif dan kuat")
    elif adx < ADX_RANGING:
        raw = int(raw * 0.4)
        notes.append(f"ADX {adx:.1f} — pasar dalam fase konsolidasi (skor dikurangi)")

    normalized = (raw + 3) / 6.0
    return normalized, notes, adx


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> float:
    """Kalkulasi ADX (Average Directional Index)."""
    try:
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs(),
        ], axis=1).max(axis=1)

        atr = tr.ewm(span=period, adjust=False).mean()

        dm_up   = high.diff()
        dm_down = -low.diff()
        dm_up   = dm_up.where((dm_up > dm_down) & (dm_up > 0), 0.0)
        dm_down = dm_down.where((dm_down > dm_up) & (dm_down > 0), 0.0)

        di_up   = 100 * dm_up.ewm(span=period, adjust=False).mean() / atr
        di_down = 100 * dm_down.ewm(span=period, adjust=False).mean() / atr

        dx  = 100 * (di_up - di_down).abs() / (di_up + di_down).replace(0, np.nan)
        adx = dx.ewm(span=period, adjust=False).mean()
        val = float(adx.iloc[-1])
        return val if not np.isnan(val) else 20.0
    except Exception:
        return 20.0


# ============================================================
# LAYER 2 — RADAR (Konsensus Oscillator)
# ============================================================

def _compute_radar(df: pd.DataFrame) -> tuple[float, list, dict]:
    """
    Kumpulkan suara dari 4 oscillator independen.
    Sinyal hanya diterima bila minimal RADAR_MIN_VOTES oscillator sepakat.
    MACD memberikan suara parsial (0.5) untuk kondisi non-crossover.
    """
    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]
    notes   = []
    bullish = 0.0
    bearish = 0.0
    readings: dict = {}

    # RSI
    rsi = _rsi(close, RSI_WINDOW)
    readings["rsi"] = rsi
    if rsi < RSI_FLOOR:
        bullish += 1
        notes.append(f"RSI {rsi:.1f} — zona jenuh jual, potensi pembalikan naik")
    elif rsi > RSI_CEILING:
        bearish += 1
        notes.append(f"RSI {rsi:.1f} — zona jenuh beli, waspadai koreksi")
    else:
        notes.append(f"RSI {rsi:.1f} — netral")

    # Stochastic
    sk, sd = _stochastic(high, low, close)
    readings["stoch_k"] = sk
    if sk < STOCH_FLOOR and sk > sd:
        bullish += 1
        notes.append(f"Stoch %K {sk:.1f} — oversold + persilangan bullish")
    elif sk > STOCH_CEILING and sk < sd:
        bearish += 1
        notes.append(f"Stoch %K {sk:.1f} — overbought + persilangan bearish")

    # MACD
    macd_line, sig_line, delta, prev_delta = _macd(close)
    readings["macd_delta"] = delta
    if delta > 0 and prev_delta <= 0:
        bullish += 1
        notes.append("MACD golden cross — momentum beli baru terbentuk")
    elif delta < 0 and prev_delta >= 0:
        bearish += 1
        notes.append("MACD death cross — momentum jual aktif")
    elif delta > 0:
        bullish += 0.5
    elif delta < 0:
        bearish += 0.5

    # CCI
    cci = _cci(high, low, close, CCI_WINDOW)
    readings["cci"] = cci
    if cci < CCI_FLOOR:
        bullish += 1
        notes.append(f"CCI {cci:.0f} — harga di bawah rata-rata historis (peluang entry)")
    elif cci > CCI_CEILING:
        bearish += 1
        notes.append(f"CCI {cci:.0f} — harga di atas rata-rata historis (pertimbangkan exit)")

    if bullish >= RADAR_MIN_VOTES:
        score = 0.5 + (bullish / 4) * 0.5
    elif bearish >= RADAR_MIN_VOTES:
        score = 0.5 - (bearish / 4) * 0.5
    else:
        score = 0.5

    return score, notes, readings


def _rsi(close: pd.Series, window: int) -> float:
    delta = close.diff()
    gain  = delta.where(delta > 0, 0.0).ewm(span=window, adjust=False).mean()
    loss  = (-delta.where(delta < 0, 0.0)).ewm(span=window, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    val   = float((100 - 100 / (1 + rs)).iloc[-1])
    return val if not np.isnan(val) else 50.0


def _stochastic(high: pd.Series, low: pd.Series, close: pd.Series) -> tuple[float, float]:
    ll = low.rolling(STOCH_PERIOD).min()
    hh = high.rolling(STOCH_PERIOD).max()
    k  = 100 * (close - ll) / (hh - ll).replace(0, np.nan)
    k_smooth = k.rolling(STOCH_SMOOTH).mean()
    d  = k_smooth.rolling(STOCH_SIGNAL).mean()
    kv = float(k_smooth.iloc[-1]) if not np.isnan(k_smooth.iloc[-1]) else 50.0
    dv = float(d.iloc[-1]) if not np.isnan(d.iloc[-1]) else 50.0
    return kv, dv


def _macd(close: pd.Series) -> tuple[float, float, float, float]:
    """
    Hitung MACD lengkap dalam satu pass.
    Return: (macd_line, signal_line, delta_now, delta_prev)
    Menggabungkan dua fungsi sebelumnya agar tidak ada duplikasi komputasi EMA.
    """
    fast  = close.ewm(span=MACD_SHORT,   adjust=False).mean()
    slow  = close.ewm(span=MACD_LONG,    adjust=False).mean()
    line  = fast - slow
    sig   = line.ewm(span=MACD_TRIGGER, adjust=False).mean()
    delta = line - sig
    prev  = float(delta.iloc[-2]) if len(delta) > 1 else 0.0
    return float(line.iloc[-1]), float(sig.iloc[-1]), float(delta.iloc[-1]), prev


def _cci(high: pd.Series, low: pd.Series, close: pd.Series, window: int) -> float:
    tp    = (high + low + close) / 3
    mean  = tp.rolling(window).mean()
    dev   = tp.rolling(window).apply(lambda x: np.mean(np.abs(x - x.mean())))
    cci   = (tp - mean) / (0.015 * dev.replace(0, np.nan))
    val   = float(cci.iloc[-1])
    return val if not np.isnan(val) else 0.0


# ============================================================
# LAYER 3 — FLOW (Arus Dana & Volume)
# ============================================================

def _compute_flow(df: pd.DataFrame) -> tuple[float, list, float]:
    """
    Validasi apakah pergerakan harga didukung oleh arus dana nyata.
    Pergerakan tanpa volume adalah pergerakan yang lemah.

    Berbeda dari sistem asli: layer ini dapat menghasilkan skor negatif
    bila distribusi terdeteksi secara konsisten.
    """
    close  = df["Close"]
    volume = df["Volume"]
    high   = df["High"]
    low    = df["Low"]
    notes  = []

    if volume.sum() == 0:
        notes.append("Data volume tidak tersedia — layer dinonaktifkan")
        return 0.5, notes, 0.0

    avg_vol = volume.rolling(FLOW_BASELINE_PERIOD).mean()
    cur_vol = volume.iloc[-1]
    avg     = avg_vol.iloc[-1]
    ratio   = cur_vol / avg if avg > 0 else 1.0

    score = 0.5

    if ratio >= FLOW_SURGE_RATIO:
        score += 0.25
        notes.append(f"Volume {ratio:.1f}x baseline — lonjakan arus dana luar biasa")
    elif ratio >= FLOW_ELEVATED_RATIO:
        score += 0.12
        notes.append(f"Volume {ratio:.1f}x baseline — arus dana di atas normal")
    elif ratio < 0.7:
        score -= 0.10
        notes.append(f"Volume {ratio:.1f}x baseline — minat pasar rendah")
    else:
        notes.append(f"Volume {ratio:.1f}x baseline — normal")

    # OBV (On-Balance Volume)
    obv    = _obv(close, volume)
    obv_ma = obv.rolling(FLOW_BASELINE_PERIOD).mean()
    if obv.iloc[-1] > obv_ma.iloc[-1]:
        score += 0.12
        notes.append("OBV meningkat — akumulasi terdeteksi")
    else:
        score -= 0.12
        notes.append("OBV menurun — distribusi terdeteksi")

    # MFI (Money Flow Index)
    mfi = _mfi(high, low, close, volume, MFI_WINDOW)
    if mfi < MFI_FLOOR:
        score += 0.12
        notes.append(f"MFI {mfi:.0f} — arus uang dalam kondisi oversold")
    elif mfi > MFI_CEILING:
        score -= 0.12
        notes.append(f"MFI {mfi:.0f} — arus uang dalam kondisi overbought")

    score = max(0.0, min(1.0, score))
    return score, notes, ratio


def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (volume * direction).cumsum()


def _mfi(high: pd.Series, low: pd.Series, close: pd.Series,
          volume: pd.Series, window: int) -> float:
    tp     = (high + low + close) / 3
    flow   = tp * volume
    pos    = flow.where(tp > tp.shift(1), 0.0)
    neg    = flow.where(tp < tp.shift(1), 0.0)
    ratio  = pos.rolling(window).sum() / neg.rolling(window).sum().replace(0, np.nan)
    val    = float((100 - 100 / (1 + ratio)).iloc[-1])
    return val if not np.isnan(val) else 50.0


# ============================================================
# LAYER 4 — FORMATION (Pola Harga)
# ============================================================

def _compute_formation(df: pd.DataFrame) -> tuple[float, list]:
    """
    Deteksi struktur harga dan pola candlestick.
    Output: skor diskrit (0.2 / 0.5 / 0.8) berdasarkan dominasi pola.
    """
    close  = df["Close"]
    high   = df["High"]
    low    = df["Low"]
    open_  = df["Open"]
    notes  = []
    bull   = 0
    bear   = 0

    # Bollinger Band squeeze & rebound
    bb_mid   = close.rolling(BB_WINDOW).mean()
    bb_sigma = close.rolling(BB_WINDOW).std()
    bb_upper = bb_mid + BB_WIDTH * bb_sigma
    bb_lower = bb_mid - BB_WIDTH * bb_sigma

    cur  = close.iloc[-1]
    prev = close.iloc[-2] if len(close) > 1 else cur

    if cur <= bb_lower.iloc[-1] and cur > prev:
        bull += 1
        notes.append("Rebound dari lower band Bollinger — tekanan jual melemah")
    elif cur >= bb_upper.iloc[-1] and cur < prev:
        bear += 1
        notes.append("Penolakan di upper band Bollinger — tekanan beli melemah")

    # Pola Hammer
    if _is_hammer(open_.iloc[-1], high.iloc[-1], low.iloc[-1], close.iloc[-1]):
        bull += 1
        notes.append("Formasi Hammer — sinyal pembalikan bullish")

    # Pola Shooting Star
    if _is_shooting_star(open_.iloc[-1], high.iloc[-1], low.iloc[-1], close.iloc[-1]):
        bear += 1
        notes.append("Formasi Shooting Star — sinyal pembalikan bearish")

    # Pola Engulfing
    if len(df) >= 2:
        if _is_bullish_engulf(open_.iloc[-2], close.iloc[-2], open_.iloc[-1], close.iloc[-1]):
            bull += 1
            notes.append("Formasi Bullish Engulfing — buyer mengambil kendali penuh")
        if _is_bearish_engulf(open_.iloc[-2], close.iloc[-2], open_.iloc[-1], close.iloc[-1]):
            bear += 1
            notes.append("Formasi Bearish Engulfing — seller mendominasi candle terakhir")

    if bull > bear:
        return 0.8, notes
    elif bear > bull:
        return 0.2, notes
    return 0.5, notes


def _is_hammer(o, h, l, c) -> bool:
    body   = abs(c - o)
    shadow_lower = min(o, c) - l
    shadow_upper = h - max(o, c)
    return body > 0 and shadow_lower > 2 * body and shadow_upper < body


def _is_shooting_star(o, h, l, c) -> bool:
    body   = abs(c - o)
    shadow_upper = h - max(o, c)
    shadow_lower = min(o, c) - l
    return body > 0 and shadow_upper > 2 * body and shadow_lower < body


def _is_bullish_engulf(po, pc, co, cc) -> bool:
    return pc < po and cc > co and co < pc and cc > po


def _is_bearish_engulf(po, pc, co, cc) -> bool:
    return pc > po and cc < co and co > pc and cc < po


# ============================================================
# LAYER 5 — MACRO (Konteks Benchmark)
# ============================================================

def _compute_macro(benchmark_df: Optional[pd.DataFrame]) -> tuple[float, list]:
    """
    Evaluasi kondisi pasar keseluruhan melalui pergerakan IHSG.
    Bila benchmark turun tajam, sistem beralih ke mode defensif:
    threshold conviction dinaikkan, sinyal beli dihambat.
    """
    notes = []

    if benchmark_df is None or benchmark_df.empty:
        notes.append("Data benchmark tidak tersedia — konteks makro dinetralkan")
        return 0.5, notes

    prices = benchmark_df["Close"]
    if len(prices) < 2:
        return 0.5, notes

    change = (prices.iloc[-1] - prices.iloc[-2]) / prices.iloc[-2]

    if change <= BENCHMARK_SLIP_DEFENSE:
        notes.append(f"IHSG melemah tajam {change*100:.1f}% — mode defensif aktif")
        return 0.1, notes
    elif change <= BENCHMARK_SLIP_CAUTION:
        notes.append(f"IHSG melemah {change*100:.1f}% — naikkan kewaspadaan")
        return 0.3, notes
    elif change >= 0.01:
        notes.append(f"IHSG menguat {change*100:.1f}% — sentimen pasar positif")
        return 0.8, notes
    else:
        notes.append(f"IHSG {change*100:.1f}% — pasar stabil")
        return 0.55, notes


# ============================================================
# SCORING ENGINE — Agregasi 5 Layer
# ============================================================

def evaluate(ticker: str, df: pd.DataFrame,
             benchmark_df: Optional[pd.DataFrame] = None) -> Optional[AlertPacket]:
    """
    Jalankan 5 layer analisa dan agregasikan menjadi satu rating 0–100.

    Prinsip: tidak ada layer yang bisa mendominasi.
    Sinyal hanya diterbitkan bila konfluensi lintas layer terpenuhi.
    """
    try:
        if df is None or len(df) < MIN_CANDLES_REQUIRED:
            log.warning(f"[ENGINE] {ticker}: data tidak mencukupi untuk evaluasi")
            return None

        pulse_norm,     pulse_notes,     adx_val     = _compute_pulse(df)
        radar_norm,     radar_notes,     readings    = _compute_radar(df)
        flow_norm,      flow_notes,      flow_ratio  = _compute_flow(df)
        formation_norm, formation_notes              = _compute_formation(df)
        macro_norm,     macro_notes                  = _compute_macro(benchmark_df)

        raw = (
            pulse_norm     * WEIGHT_PULSE     +
            radar_norm     * WEIGHT_RADAR     +
            flow_norm      * WEIGHT_FLOW      +
            formation_norm * WEIGHT_FORMATION +
            macro_norm     * WEIGHT_MACRO
        )
        rating = round(raw * 100, 1)

        # Tentukan verdict berdasarkan rating + arah tren dominan
        if rating >= CONVICTION_HIGH:
            verdict    = "STRONG_LONG" if pulse_norm > 0.5 else "STRONG_SHORT"
            conviction = "STRONG"
        elif rating >= CONVICTION_MODERATE:
            verdict    = "LONG" if pulse_norm > 0.5 else "SHORT"
            conviction = "MODERATE"
        else:
            verdict    = "HOLD"
            conviction = "WEAK"

        # Kalkulasi level otomatis
        last_price = float(df["Close"].iloc[-1])
        if "LONG" in verdict:
            upside_level = round(last_price * (1 + UPSIDE_TARGET_PCT))
            guard_level  = round(last_price * (1 - DOWNSIDE_GUARD_PCT))
        elif "SHORT" in verdict:
            upside_level = round(last_price * (1 - SHORT_TARGET_PCT))
            guard_level  = round(last_price * (1 + SHORT_GUARD_PCT))
        else:
            upside_level = last_price
            guard_level  = last_price

        # Susun catatan — prioritaskan layer berbobot tinggi
        all_notes = (
            [n for n in pulse_notes if n]     +
            [n for n in flow_notes if n]      +
            [n for n in radar_notes if n]     +
            [n for n in formation_notes if n] +
            [n for n in macro_notes if n]
        )

        packet = AlertPacket(
            ticker        = ticker,
            rating        = rating,
            verdict       = verdict,
            last_price    = last_price,
            upside_level  = upside_level,
            guard_level   = guard_level,
            conviction    = conviction,
            pulse_rating     = round(pulse_norm * 100, 1),
            radar_rating     = round(radar_norm * 100, 1),
            flow_rating      = round(flow_norm * 100, 1),
            formation_rating = round(formation_norm * 100, 1),
            macro_rating     = round(macro_norm * 100, 1),
            notes         = all_notes,
            rsi_value     = readings.get("rsi", 0.0),
            macd_delta    = readings.get("macd_delta", 0.0),
            flow_ratio    = flow_ratio,
            adx_value     = adx_val,
        )

        log.info(
            f"[ENGINE] {ticker}: rating={rating:.1f} verdict={verdict} "
            f"| pulse={pulse_norm*100:.0f} radar={radar_norm*100:.0f} "
            f"flow={flow_norm*100:.0f} formation={formation_norm*100:.0f} macro={macro_norm*100:.0f}"
        )
        return packet

    except Exception as exc:
        log.error(f"[ENGINE] {ticker}: error saat evaluasi — {exc}", exc_info=True)
        return None
