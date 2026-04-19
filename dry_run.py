"""
NEXUS — Dry Run Simulator
=========================
Menjalankan seluruh pipeline NEXUS menggunakan data sintetis,
tanpa koneksi ke server manapun (Supabase, Telegram, yfinance, Twelve Data).

Semua lapisan eksternal digantikan stub memori.
Engine, dispatcher (format pesan), dan ledger (logika filter)
berjalan dengan kode asli.

Cara pakai:
    python dry_run.py

Kebutuhan:
    pip install pandas numpy
    (sudah termasuk dalam requirements.txt NEXUS)
"""

import sys
import os
import logging
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# ─── Path setup ──────────────────────────────────────────────────────────────
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("DRY_RUN")

# ─── Import library data sebelum mocking ─────────────────────────────────────
import pandas as pd
import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
# BAGIAN 1: GENERATOR DATA SINTETIS
# ─────────────────────────────────────────────────────────────────────────────

def _timestamps(n: int) -> pd.DatetimeIndex:
    """Buat n timestamp mundur 5 menit, berakhir di 'sekarang'."""
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    times = [now - timedelta(minutes=5 * (n - i - 1)) for i in range(n)]
    return pd.DatetimeIndex(times, tz=timezone.utc)


def buat_skenario_bullish(n: int = 70, seed: int = 42) -> pd.DataFrame:
    """
    Tren naik yang jelas:
    - Harga naik bertahap dari 9000 → 9600
    - EMA20 > EMA50 > EMA100 (bullish alignment)
    - RSI akan berada di zona pemulihan (35–45)
    - Volume melonjak di 10 candle terakhir (2x normal)
    - Diharapkan menghasilkan verdict LONG atau STRONG_LONG
    """
    rng = np.random.default_rng(seed)
    base  = np.linspace(9000, 9600, n)
    noise = rng.normal(0, 30, n)
    close = base + noise
    close = np.maximum(close, 100)

    body   = rng.uniform(20, 80, n)
    high   = close + body + rng.uniform(5, 20, n)
    low    = close - body - rng.uniform(5, 20, n)
    open_  = close - rng.normal(0, 20, n)

    volume = rng.uniform(800_000, 1_200_000, n)
    volume[-10:] = rng.uniform(2_000_000, 2_800_000, 10)   # lonjakan akhir

    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=_timestamps(n),
    )


def buat_skenario_bearish(n: int = 70, seed: int = 99) -> pd.DataFrame:
    """
    Tren turun yang jelas:
    - Harga turun dari 5400 → 4800
    - RSI akan berada di zona overbought kemudian jatuh
    - Volume normal lalu turun (distribusi)
    - Diharapkan menghasilkan verdict SHORT atau STRONG_SHORT
    """
    rng = np.random.default_rng(seed)
    base  = np.linspace(5400, 4800, n)
    noise = rng.normal(0, 25, n)
    close = base + noise
    close = np.maximum(close, 100)

    body   = rng.uniform(20, 60, n)
    high   = close + body + rng.uniform(5, 15, n)
    low    = close - body - rng.uniform(5, 15, n)
    open_  = close + rng.normal(0, 15, n)

    volume = rng.uniform(600_000, 900_000, n)
    volume[-15:] = rng.uniform(300_000, 500_000, 15)   # penurunan volume (distribusi)

    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=_timestamps(n),
    )


def buat_skenario_sideways(n: int = 70, seed: int = 7) -> pd.DataFrame:
    """
    Pasar konsolidasi:
    - Harga bergerak datar di sekitar 3200
    - ADX rendah → PULSE dikempiskan
    - Diharapkan menghasilkan verdict HOLD
    """
    rng = np.random.default_rng(seed)
    close = 3200 + rng.normal(0, 40, n)
    close = np.maximum(close, 100)

    body   = rng.uniform(10, 40, n)
    high   = close + body + rng.uniform(5, 15, n)
    low    = close - body - rng.uniform(5, 15, n)
    open_  = close - rng.normal(0, 10, n)
    volume = rng.uniform(400_000, 700_000, n)

    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=_timestamps(n),
    )


def buat_benchmark(n: int = 70, arah: str = "naik") -> pd.DataFrame:
    """Data IHSG sintetis untuk layer MACRO."""
    rng = np.random.default_rng(1)
    if arah == "naik":
        close = np.linspace(7200, 7350, n) + rng.normal(0, 20, n)
    elif arah == "turun":
        close = np.linspace(7300, 7000, n) + rng.normal(0, 25, n)
    else:
        close = np.full(n, 7200.0) + rng.normal(0, 15, n)

    return pd.DataFrame(
        {"Close": close},
        index=_timestamps(n),
    )


# ─────────────────────────────────────────────────────────────────────────────
# BAGIAN 2: STUB SUPABASE (IN-MEMORY)
# ─────────────────────────────────────────────────────────────────────────────

class _SupabaseMemory:
    """Database dalam memori yang meniru perilaku Supabase REST API."""

    def __init__(self):
        self.alert_log     : list[dict] = []
        self.pending_alerts: list[dict] = []

    def reset(self):
        self.alert_log.clear()
        self.pending_alerts.clear()

    def print_state(self):
        log.info(f"  [DB] alert_log     : {len(self.alert_log)} record")
        log.info(f"  [DB] pending_alerts: {len(self.pending_alerts)} record")
        for r in self.alert_log:
            log.info(f"         ↳ {r['ticker']} | {r['verdict']} | {r['rating']:.1f} | Rp {r['price']:,.0f}")


_db = _SupabaseMemory()


def _mock_requests_get(url: str, **kwargs) -> MagicMock:
    """
    Simulasi Supabase REST GET.
    Ledger selalu menggunakan len(resp.json()) — tidak ada endpoint count() terpisah.
    Kembalikan list yang sudah difilter agar len() akurat.
    """
    resp = MagicMock()
    resp.status_code = 200

    params = kwargs.get("params", {})

    if "alert_log" in url:
        now = datetime.now(timezone.utc)

        # Baca filter ticker dan verdict (format: "eq.BBCA.JK")
        raw_ticker  = str(params.get("ticker",  ""))
        raw_verdict = str(params.get("verdict", ""))
        raw_sent_at = str(params.get("sent_at", ""))  # format: "gte.2026-04-19"

        ticker  = raw_ticker.removeprefix("eq.")  if raw_ticker  else ""
        verdict = raw_verdict.removeprefix("eq.") if raw_verdict else ""

        # Filter records yang cocok
        hasil = []
        for r in _db.alert_log:
            if ticker  and r["ticker"]  != ticker:  continue
            if verdict and r["verdict"] != verdict: continue
            # Filter sent_at gte (cooldown check pakai isoformat datetime, count_today pakai date)
            if raw_sent_at:
                cutoff_str = raw_sent_at.removeprefix("gte.")
                try:
                    if "T" in cutoff_str:
                        cutoff_dt = datetime.fromisoformat(cutoff_str).astimezone(timezone.utc)
                    else:
                        # hanya tanggal, misalnya "2026-04-19"
                        cutoff_dt = datetime.fromisoformat(cutoff_str + "T00:00:00+00:00")
                    if r["sent_at"] < cutoff_dt:
                        continue
                except Exception:
                    pass
            hasil.append(r)

        resp.json.return_value = hasil

    elif "pending_alerts" in url:
        raw_ticker  = str(params.get("ticker",  ""))
        raw_verdict = str(params.get("verdict", ""))

        ticker  = raw_ticker.removeprefix("eq.")  if raw_ticker  else ""
        verdict = raw_verdict.removeprefix("eq.") if raw_verdict else ""

        hasil = [
            r for r in _db.pending_alerts
            if (not ticker  or r["ticker"]  == ticker)
            and (not verdict or r["verdict"] == verdict)
        ]
        resp.json.return_value = hasil

    else:
        resp.json.return_value = []

    return resp


def _mock_requests_post(url: str, **kwargs) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 201

    data = kwargs.get("json", {})
    now  = datetime.now(timezone.utc)

    if "alert_log" in url:
        _db.alert_log.append({
            "ticker" : data.get("ticker"),
            "verdict": data.get("verdict"),
            "rating" : data.get("rating"),
            "price"  : data.get("price"),
            "sent_at": now,
        })
    elif "pending_alerts" in url:
        _db.pending_alerts.append({
            "ticker"    : data.get("ticker"),
            "verdict"   : data.get("verdict"),
            "rating"    : data.get("rating"),
            "created_at": now,
        })

    return resp


def _mock_requests_delete(url: str, **kwargs) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    # Purge semua pending (simulasi purge_expired_pending)
    _db.pending_alerts.clear()
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# BAGIAN 3: STUB TELEGRAM (PRINT KE CONSOLE)
# ─────────────────────────────────────────────────────────────────────────────

_pesan_terkirim: list[str] = []

def _mock_send_telegram(url: str, **kwargs) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"ok": True}

    data = kwargs.get("json", {})
    text = data.get("text", "")

    _pesan_terkirim.append(text)
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# BAGIAN 4: HELPER — JALANKAN SATU SKENARIO
# ─────────────────────────────────────────────────────────────────────────────

SEPARATOR = "═" * 60


def jalankan_skenario(
    label     : str,
    ticker    : str,
    df        : pd.DataFrame,
    benchmark : pd.DataFrame,
    extra_tickers: dict | None = None,
):
    """
    Jalankan engine + dispatcher + ledger untuk satu instrumen.
    extra_tickers: dict tambahan {ticker: df} yang ikut diproses.
    """
    from core.engine     import evaluate
    from core.dispatcher import build_alert_message, dispatch_session_summary
    from core.ledger     import (
        is_on_cooldown, count_alerts_today, record_alert,
        get_pending_count, register_pending,
        purge_expired_pending, get_all_alerts_today,
    )
    from config.params   import (
        CONVICTION_HIGH, CONVICTION_MODERATE,
        MAX_DAILY_ALERTS, COOLDOWN_PER_TICKER, CONFIRM_ROUNDS,
    )

    print(f"\n{SEPARATOR}")
    print(f"  SKENARIO: {label}")
    print(f"  Instrumen: {ticker}  |  Candles: {len(df)}")
    print(SEPARATOR)

    # Reset state DB untuk skenario bersih
    _db.reset()
    _pesan_terkirim.clear()

    universe = {ticker: df}
    if extra_tickers:
        universe.update(extra_tickers)

    alerts_dispatched = []

    for tkr, data in universe.items():
        print(f"\n  ▶ Evaluasi: {tkr}")

        # ── Engine ──────────────────────────────────────────────
        packet = evaluate(tkr, data, benchmark)

        if packet is None:
            print(f"    ✗ Engine: data tidak cukup atau error")
            continue

        print(f"    Rating    : {packet.rating:.1f}/100")
        print(f"    Verdict   : {packet.verdict}")
        print(f"    Conviction: {packet.conviction}")
        print(f"    Harga     : Rp {packet.last_price:,.0f}")
        print(f"    Sub-skor  : PULSE={packet.pulse_rating:.0f} | RADAR={packet.radar_rating:.0f} | "
              f"FLOW={packet.flow_rating:.0f} | FORM={packet.formation_rating:.0f} | MACRO={packet.macro_rating:.0f}")
        print(f"    RSI={packet.rsi_value:.1f}  |  MACD delta={packet.macd_delta:.4f}  |  ADX={packet.adx_value:.1f}")

        if packet.verdict == "HOLD":
            print(f"    ✗ Filter: HOLD — tidak ada sinyal")
            continue

        # ── Filter: cooldown ─────────────────────────────────────
        cd = is_on_cooldown(tkr, packet.verdict, COOLDOWN_PER_TICKER)
        if cd is None:
            print(f"    ✗ Filter: cooldown tidak terverifikasi (DB error)")
            continue
        if cd:
            print(f"    ✗ Filter: cooldown aktif")
            continue

        # ── Filter: batas harian ─────────────────────────────────
        total_today = count_alerts_today()
        if total_today is None or (total_today + len(alerts_dispatched)) >= MAX_DAILY_ALERTS:
            print(f"    ✗ Filter: batas harian tercapai")
            break

        # ── Filter: konfirmasi 2 scan ────────────────────────────
        pending = get_pending_count(tkr, packet.verdict)
        if pending < (CONFIRM_ROUNDS - 1):
            register_pending(tkr, packet.verdict, packet.rating)
            print(f"    ⏳ Filter: scan ke-1, daftar pending (belum dispatch)")
            continue

        # ── Dispatch ─────────────────────────────────────────────
        pesan = build_alert_message(packet)
        # Telegram dipalsukan — pesan dicetak ke konsol
        _pesan_terkirim.append(pesan)
        record_alert(tkr, packet.verdict, packet.rating, packet.last_price)
        alerts_dispatched.append(packet)
        print(f"    ✓ DISPATCH — alert dikirim ke Telegram")

    # ── Tampilkan pesan Telegram yang "terkirim" ─────────────────
    if _pesan_terkirim:
        print(f"\n  {'─'*56}")
        print(f"  PREVIEW PESAN TELEGRAM ({len(_pesan_terkirim)} pesan):")
        print(f"  {'─'*56}")
        for i, p in enumerate(_pesan_terkirim, 1):
            # Bersihkan tag HTML untuk tampilan konsol
            clean = p.replace("<b>", "").replace("</b>", "")
            print(f"\n  [Pesan {i}]")
            for baris in clean.strip().split("\n"):
                print(f"    {baris}")
    else:
        print(f"\n  ── Tidak ada pesan yang terkirim di skenario ini")

    # ── State DB akhir ───────────────────────────────────────────
    print(f"\n  [Status Database In-Memory]")
    _db.print_state()

    return alerts_dispatched


# ─────────────────────────────────────────────────────────────────────────────
# BAGIAN 5: TEST KONFIRMASI 2-SCAN
# ─────────────────────────────────────────────────────────────────────────────

def test_konfirmasi_dua_scan():
    """
    Simulasi 2 siklus scan berturut-turut.
    Scan 1: sinyal pertama → masuk pending, tidak dispatch.
    Scan 2: sinyal muncul lagi → lolos filter, dispatch.
    """
    from core.engine     import evaluate
    from core.dispatcher import build_alert_message
    from core.ledger     import (
        is_on_cooldown, count_alerts_today, record_alert,
        get_pending_count, register_pending, purge_expired_pending,
    )
    from config.params   import MAX_DAILY_ALERTS, CONFIRM_ROUNDS

    print(f"\n{SEPARATOR}")
    print(f"  TEST: Konfirmasi 2-Scan (anti-noise)")
    print(SEPARATOR)

    _db.reset()
    _pesan_terkirim.clear()

    ticker    = "BBCA.JK"
    df        = buat_skenario_bullish()
    benchmark = buat_benchmark(arah="naik")

    packet = evaluate(ticker, df, benchmark)
    if packet is None or packet.verdict == "HOLD":
        print(f"  ✗ Engine tidak menghasilkan sinyal untuk test ini — gunakan data berbeda")
        return

    print(f"\n  [SCAN 1] verdict={packet.verdict} rating={packet.rating:.1f}")
    pending_awal = get_pending_count(ticker, packet.verdict)
    if pending_awal < (CONFIRM_ROUNDS - 1):
        register_pending(ticker, packet.verdict, packet.rating)
        print(f"  → Sinyal pertama masuk pending. Belum dispatch. (pending sekarang: 1)")

    print(f"\n  [SCAN 2] sinyal yang sama muncul lagi...")
    pending_sekarang = get_pending_count(ticker, packet.verdict)
    if pending_sekarang >= (CONFIRM_ROUNDS - 1):
        pesan = build_alert_message(packet)
        _pesan_terkirim.append(pesan)
        record_alert(ticker, packet.verdict, packet.rating, packet.last_price)
        print(f"  → DISPATCH ✓ — konfirmasi 2 scan terpenuhi")
    else:
        print(f"  ✗ Masih belum cukup konfirmasi")

    print(f"\n  [Status DB setelah 2 scan]")
    _db.print_state()


# ─────────────────────────────────────────────────────────────────────────────
# BAGIAN 6: TEST COOLDOWN
# ─────────────────────────────────────────────────────────────────────────────

def test_cooldown():
    """
    Simulasi: alert dikirim → scan berikutnya untuk ticker yang sama harus diblokir cooldown.
    """
    from core.ledger import is_on_cooldown, record_alert, count_alerts_today

    print(f"\n{SEPARATOR}")
    print(f"  TEST: Cooldown Per-Ticker")
    print(SEPARATOR)

    _db.reset()

    ticker  = "TLKM.JK"
    verdict = "LONG"
    harga   = 3875.0

    print(f"  Catat alert pertama untuk {ticker}...")
    record_alert(ticker, verdict, 72.5, harga)

    cd = is_on_cooldown(ticker, verdict, cooldown_minutes=60)
    status = "✓ BLOKIR (benar)" if cd else "✗ LOLOS (salah — cooldown tidak berfungsi)"
    print(f"  Cek cooldown 60 menit → {status}")

    cd2 = is_on_cooldown(ticker, "SHORT", cooldown_minutes=60)
    status2 = "✓ LOLOS (benar — beda verdict)" if not cd2 else "✗ BLOKIR (salah — seharusnya lolos)"
    print(f"  Cek cooldown ticker sama, verdict berbeda (SHORT) → {status2}")

    cd3 = is_on_cooldown("BBRI.JK", verdict, cooldown_minutes=60)
    status3 = "✓ LOLOS (benar — beda ticker)" if not cd3 else "✗ BLOKIR (salah — seharusnya lolos)"
    print(f"  Cek cooldown ticker berbeda (BBRI) verdict sama → {status3}")


# ─────────────────────────────────────────────────────────────────────────────
# BAGIAN 7: TEST BATAS HARIAN
# ─────────────────────────────────────────────────────────────────────────────

def test_batas_harian():
    """
    Simulasi: isi alert_log sampai penuh, verifikasi count_alerts_today.
    """
    from core.ledger import count_alerts_today, record_alert
    from config.params import MAX_DAILY_ALERTS

    print(f"\n{SEPARATOR}")
    print(f"  TEST: Batas Harian ({MAX_DAILY_ALERTS} alert/hari)")
    print(SEPARATOR)

    _db.reset()

    tickers = ["BBCA.JK", "BBRI.JK", "TLKM.JK", "ASII.JK",
               "BMRI.JK", "UNVR.JK", "ICBP.JK", "GGRM.JK"]

    for i, t in enumerate(tickers):
        record_alert(t, "LONG", 70.0 + i, 5000 + i * 100)

    total = count_alerts_today()
    print(f"  Alert tercatat hari ini: {total}")
    print(f"  Batas maksimum         : {MAX_DAILY_ALERTS}")

    if total is not None and total >= MAX_DAILY_ALERTS:
        print(f"  ✓ Sistem akan memblokir alert baru (benar)")
    else:
        print(f"  ✗ Batas harian tidak berfungsi dengan benar")


# ─────────────────────────────────────────────────────────────────────────────
# BAGIAN 8: MAIN — PATCH & EKSEKUSI
# ─────────────────────────────────────────────────────────────────────────────

def _buat_mock_requests():
    """
    Buat mock modul requests yang mengalihkan semua panggilan ke stub.
    Deteksi otomatis: Supabase → in-memory DB, Telegram → print.
    """
    mock_requests = MagicMock()

    def smart_get(url, **kwargs):
        return _mock_requests_get(url, **kwargs)

    def smart_post(url, **kwargs):
        if "api.telegram.org" in url:
            return _mock_send_telegram(url, **kwargs)
        return _mock_requests_post(url, **kwargs)

    def smart_delete(url, **kwargs):
        return _mock_requests_delete(url, **kwargs)

    mock_requests.get    = smart_get
    mock_requests.post   = smart_post
    mock_requests.delete = smart_delete
    return mock_requests


def main():
    print(f"\n{'═'*60}")
    print(f"  NEXUS DRY RUN SIMULATOR")
    print(f"  Semua server dipalsukan — berjalan 100% offline")
    print(f"{'═'*60}\n")

    mock_req = _buat_mock_requests()

    # Patch semua modul yang menggunakan requests dan env vars eksternal
    with patch.dict(os.environ, {
        "SUPABASE_URL"        : "https://mock.supabase.co",
        "SUPABASE_KEY"        : "mock-service-key",
        "TELEGRAM_BOT_TOKEN"  : "0000000000:mock-token",
        "TELEGRAM_CHAT_ID"    : "-100123456789",
        "TWELVEDATA_API_KEY"  : "",    # kosong = Twelve Data tidak dipakai
    }):
        with patch("core.ledger.requests",     mock_req), \
             patch("core.dispatcher.requests", mock_req):

            # ── Skenario 1: Bullish ──────────────────────────────────
            jalankan_skenario(
                label     = "TREN NAIK (harapan: LONG / STRONG_LONG)",
                ticker    = "BBCA.JK",
                df        = buat_skenario_bullish(),
                benchmark = buat_benchmark(arah="naik"),
            )

            # ── Skenario 2: Bearish ──────────────────────────────────
            jalankan_skenario(
                label     = "TREN TURUN (harapan: SHORT / STRONG_SHORT)",
                ticker    = "BBRI.JK",
                df        = buat_skenario_bearish(),
                benchmark = buat_benchmark(arah="turun"),
            )

            # ── Skenario 3: Sideways ─────────────────────────────────
            jalankan_skenario(
                label     = "PASAR SIDEWAYS (harapan: HOLD — tidak ada alert)",
                ticker    = "TLKM.JK",
                df        = buat_skenario_sideways(),
                benchmark = buat_benchmark(arah="flat"),
            )

            # ── Skenario 4: Multi-instrumen dalam satu siklus ────────
            jalankan_skenario(
                label = "MULTI-INSTRUMEN (3 saham, 1 siklus)",
                ticker = "ASII.JK",
                df     = buat_skenario_bullish(seed=55),
                benchmark = buat_benchmark(arah="naik"),
                extra_tickers = {
                    "BMRI.JK": buat_skenario_bearish(seed=77),
                    "UNVR.JK": buat_skenario_sideways(seed=13),
                },
            )

            # ── Test logika filter ────────────────────────────────────
            test_konfirmasi_dua_scan()
            test_cooldown()
            test_batas_harian()

    print(f"\n{'═'*60}")
    print(f"  DRY RUN SELESAI")
    print(f"  Tidak ada request nyata yang keluar.")
    print(f"{'═'*60}\n")


if __name__ == "__main__":
    main()
