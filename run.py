"""
NEXUS — Market Intelligence Engine
Entry point utama. Dieksekusi oleh GitHub Actions setiap siklus polling.

Alur eksekusi:
  1. Validasi jam sesi perdagangan IDX
  2. Konektivitas Supabase diverifikasi (fail-safe: batal bila tidak bisa konek)
  3. Bersihkan pending alerts kadaluarsa
  4. Ambil data benchmark (IHSG) + seluruh universe LQ45
  5. Evaluasi setiap instrumen via 5-layer engine
  6. Filter: cooldown, batas harian, konfirmasi multi-scan
  7. Dispatch alert yang lolos filter ke Telegram
  8. Kirim ringkasan sesi bila mendekati penutupan
"""

import logging
import sys
from datetime import datetime, timezone, timedelta

from config.params import (
    SESSION_OPEN_HOUR, SESSION_OPEN_MINUTE,
    SESSION_CLOSE_HOUR, SESSION_CLOSE_MINUTE,
    MAX_DAILY_ALERTS, COOLDOWN_PER_TICKER, CONFIRM_ROUNDS,
)
from config.universe import LQ45_UNIVERSE
from core.fetcher    import fetch_universe, fetch_benchmark
from core.engine     import evaluate
from core.dispatcher import dispatch_alert, dispatch_session_summary, inter_message_pause
from core.ledger     import (
    is_on_cooldown, count_alerts_today, record_alert,
    get_pending_count, register_pending, purge_expired_pending,
    get_all_alerts_today,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("NEXUS")

WIB = timezone(timedelta(hours=7))


# ============================================================
# Validasi Waktu Sesi
# ============================================================

def _is_session_active() -> bool:
    """Cek apakah saat ini dalam jam operasional IDX (Senin–Jumat)."""
    now = datetime.now(WIB)

    if now.weekday() >= 5:
        log.info(f"Hari libur ({now.strftime('%A')}) — sesi tidak aktif")
        return False

    open_time  = now.replace(hour=SESSION_OPEN_HOUR,  minute=SESSION_OPEN_MINUTE,  second=0)
    close_time = now.replace(hour=SESSION_CLOSE_HOUR, minute=SESSION_CLOSE_MINUTE, second=0)

    if open_time <= now <= close_time:
        return True

    log.info(f"Di luar jam sesi (sekarang {now.strftime('%H:%M')} WIB) — engine idle")
    return False


def _is_approaching_close() -> bool:
    """True bila dalam 10 menit menjelang penutupan sesi — trigger ringkasan harian."""
    now        = datetime.now(WIB)
    close_time = now.replace(hour=SESSION_CLOSE_HOUR, minute=SESSION_CLOSE_MINUTE, second=0)
    window     = close_time - timedelta(minutes=10)
    return window <= now <= close_time


# ============================================================
# Orchestrator Utama
# ============================================================

def run():
    log.info("=" * 55)
    log.info("  NEXUS Market Intelligence Engine")
    log.info(f"  Siklus: {datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S')} WIB")
    log.info("=" * 55)

    if not _is_session_active():
        log.info("Engine berhenti — di luar sesi perdagangan.")
        return

    # --------------------------------------------------------
    # Verifikasi konektivitas ledger (fail-safe)
    # --------------------------------------------------------
    alerts_today = count_alerts_today()
    if alerts_today is None:
        log.critical(
            "Supabase tidak dapat dijangkau — siklus dibatalkan. "
            "Pengiriman alert tanpa cek cooldown berpotensi spam."
        )
        sys.exit(1)  # Keluar dengan error agar GitHub Actions mencatat kegagalan

    if alerts_today >= MAX_DAILY_ALERTS:
        log.info(f"Batas harian tercapai ({MAX_DAILY_ALERTS} alert) — scan tetap jalan, dispatch dinonaktifkan")

    # --------------------------------------------------------
    # Bersihkan pending alerts kadaluarsa
    # --------------------------------------------------------
    purge_expired_pending(max_age_minutes=30)

    # --------------------------------------------------------
    # Pengambilan data
    # --------------------------------------------------------
    log.info("Mengambil data benchmark IHSG...")
    benchmark_df = fetch_benchmark()

    log.info(f"Mengambil data {len(LQ45_UNIVERSE)} instrumen LQ45...")
    universe_data = fetch_universe()
    log.info(f"Berhasil: {len(universe_data)}/{len(LQ45_UNIVERSE)} instrumen")

    # --------------------------------------------------------
    # Evaluasi & dispatch
    # --------------------------------------------------------
    dispatched_this_cycle: list = []

    for ticker, df in universe_data.items():
        packet = evaluate(ticker, df, benchmark_df)

        if packet is None:
            continue

        if packet.verdict == "HOLD":
            continue

        # --- Cek cooldown (fail-safe) ---
        cooldown_status = is_on_cooldown(ticker, packet.verdict, COOLDOWN_PER_TICKER)
        if cooldown_status is None:
            log.error(f"Supabase tidak responsif saat cek cooldown {ticker} — skip ticker ini")
            continue
        if cooldown_status:
            continue

        # --- Cek batas harian ---
        total_sent = alerts_today + len(dispatched_this_cycle)
        if total_sent >= MAX_DAILY_ALERTS:
            log.info(f"Batas harian tercapai — {ticker} skip")
            continue

        # --- Sistem konfirmasi multi-scan ---
        pending = get_pending_count(ticker, packet.verdict)
        if pending < CONFIRM_ROUNDS - 1:
            register_pending(ticker, packet.verdict, packet.rating)
            log.info(
                f"{ticker} ({packet.verdict}, rating={packet.rating:.1f}) — "
                f"menunggu konfirmasi scan berikutnya ({pending + 1}/{CONFIRM_ROUNDS})"
            )
            continue

        # --- Dispatch alert ---
        log.info(f"DISPATCH → {ticker} {packet.verdict} rating={packet.rating:.1f}")
        success = dispatch_alert(packet)

        if success:
            record_alert(ticker, packet.verdict, packet.rating, packet.last_price)
            dispatched_this_cycle.append(packet)
            inter_message_pause()

    log.info(f"Alert terkirim siklus ini: {len(dispatched_this_cycle)}")

    # --------------------------------------------------------
    # Ringkasan sesi (mendekati penutupan)
    # --------------------------------------------------------
    if _is_approaching_close():
        log.info("Mendekati penutupan sesi — mengirim ringkasan harian...")
        all_today = get_all_alerts_today()
        dispatch_session_summary(all_today, len(universe_data))

    log.info("Siklus selesai.")


if __name__ == "__main__":
    run()
