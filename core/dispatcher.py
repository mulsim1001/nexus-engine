"""
NEXUS — Dispatcher
Pengiriman alert ke Telegram dengan retry otomatis dan rate limiting.

Perbaikan dari varian sebelumnya:
  - Retry hingga 3 kali dengan jeda eksponensial
  - Delay antar pesan untuk menghindari rate limit Telegram
  - Catatan teratas dipilih berdasarkan relevansi layer, bukan urutan array
  - Format pesan menggunakan terminologi NEXUS
"""

import os
import time
import logging
import requests
from datetime import datetime, timezone, timedelta
from core.engine import AlertPacket

log = logging.getLogger(__name__)

WIB = timezone(timedelta(hours=7))

_TELEGRAM_ENDPOINT = "https://api.telegram.org/bot{token}/sendMessage"
_MAX_RETRY         = 3
_RETRY_BASE_DELAY  = 2      # detik — jeda awal, berlipat ganda tiap retry
_INTER_MESSAGE_GAP = 3      # detik — jeda antar pesan berurutan


_VERDICT_BADGE = {
    "STRONG_LONG":  "🟢",
    "LONG":         "🔵",
    "HOLD":         "⚪",
    "SHORT":        "🟠",
    "STRONG_SHORT": "🔴",
}

_CONVICTION_LABEL = {
    "STRONG":   "TINGGI",
    "MODERATE": "SEDANG",
    "WEAK":     "RENDAH",
}


def _credentials() -> tuple[str, str]:
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        raise EnvironmentError("TELEGRAM_BOT_TOKEN atau TELEGRAM_CHAT_ID tidak ditemukan di environment")
    return token, chat_id


def _rupiah(amount: float) -> str:
    if amount >= 1000:
        return f"Rp {amount:,.0f}"
    return f"Rp {amount:.2f}"


def build_alert_message(packet: AlertPacket) -> str:
    """Susun pesan alert Telegram dalam format NEXUS."""
    badge     = _VERDICT_BADGE.get(packet.verdict, "⚪")
    label     = packet.verdict.replace("_", " ")
    conv_text = _CONVICTION_LABEL.get(packet.conviction, packet.conviction)
    code      = packet.ticker.replace(".JK", "")

    if packet.last_price > 0:
        up_pct  = (packet.upside_level - packet.last_price) / packet.last_price * 100
        grd_pct = (packet.guard_level  - packet.last_price) / packet.last_price * 100
        up_str  = f"{_rupiah(packet.upside_level)} ({up_pct:+.1f}%)"
        grd_str = f"{_rupiah(packet.guard_level)} ({grd_pct:+.1f}%)"
    else:
        up_str  = _rupiah(packet.upside_level)
        grd_str = _rupiah(packet.guard_level)

    top_notes    = packet.notes[:4]   # urutan sudah diprioritaskan di engine: Pulse→Flow→Radar→Formation→Macro
    notes_block  = "\n".join([f"  ▸ {n}" for n in top_notes]) if top_notes else "  ▸ —"
    now_str      = datetime.now(WIB).strftime("%H:%M WIB")

    message = (
        f"{badge} <b>{label}</b>\n"
        f"{'─' * 24}\n"
        f"🏷 <b>{code}</b>\n"
        f"💹 Harga: {_rupiah(packet.last_price)}\n"
        f"📊 Rating: <b>{packet.rating:.0f}/100</b> — Conviction: {conv_text}\n"
        f"\n"
        f"<b>SINYAL:</b>\n"
        f"{notes_block}\n"
        f"\n"
        f"  Pulse (Tren):    {packet.pulse_rating:.0f}/100\n"
        f"  Radar (Momentum): {packet.radar_rating:.0f}/100\n"
        f"  Flow  (Volume):  {packet.flow_rating:.0f}/100\n"
        f"\n"
        f"🎯 Target:    {up_str}\n"
        f"🛡 Guard:     {grd_str}\n"
        f"⏱ Evaluasi:  {now_str}\n"
        f"{'─' * 24}\n"
        f"<i>⚠ Analisa algoritmik — bukan saran investasi. Lakukan riset mandiri.</i>"
    )
    return message


def _send_with_retry(token: str, chat_id: str, message: str) -> bool:
    """
    Kirim satu pesan ke Telegram dengan retry eksponensial.
    Gagal permanen setelah _MAX_RETRY percobaan.
    """
    url = _TELEGRAM_ENDPOINT.format(token=token)
    payload = {
        "chat_id":                chat_id,
        "text":                   message,
        "parse_mode":             "HTML",
        "disable_web_page_preview": True,
    }

    for attempt in range(1, _MAX_RETRY + 1):
        try:
            resp = requests.post(url, json=payload, timeout=10)
            resp.raise_for_status()
            return True

        except requests.exceptions.HTTPError as exc:
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", _RETRY_BASE_DELAY * attempt))
                log.warning(f"[DISPATCHER] Rate limited oleh Telegram — tunggu {retry_after}s")
                time.sleep(retry_after)
            else:
                log.error(f"[DISPATCHER] HTTP error percobaan {attempt}: {exc}")
                if attempt < _MAX_RETRY:
                    time.sleep(_RETRY_BASE_DELAY * attempt)

        except requests.exceptions.RequestException as exc:
            log.warning(f"[DISPATCHER] Percobaan {attempt}/{_MAX_RETRY} gagal: {exc}")
            if attempt < _MAX_RETRY:
                time.sleep(_RETRY_BASE_DELAY * attempt)

    log.error(f"[DISPATCHER] Semua {_MAX_RETRY} percobaan gagal — pesan tidak terkirim")
    return False


def dispatch_alert(packet: AlertPacket) -> bool:
    """
    Kirim satu alert ke Telegram.
    Return True bila berhasil terkirim.
    """
    try:
        token, chat_id = _credentials()
        message = build_alert_message(packet)
        success = _send_with_retry(token, chat_id, message)
        if success:
            log.info(f"[DISPATCHER] Alert {packet.ticker} ({packet.verdict}) terkirim ✓")
        return success

    except EnvironmentError as exc:
        log.error(f"[DISPATCHER] Konfigurasi error: {exc}")
        return False


def dispatch_session_summary(alerts: list[dict], instruments_scanned: int) -> bool:
    """
    Kirim ringkasan sesi perdagangan di akhir hari.
    Menerima list dict dari Supabase: { ticker, verdict, rating, price, sent_at }
    """
    try:
        token, chat_id = _credentials()
        today = datetime.now(WIB).strftime("%d %b %Y")

        long_alerts  = [a for a in alerts if "LONG"  in a.get("verdict", "")]
        short_alerts = [a for a in alerts if "SHORT" in a.get("verdict", "")]

        def _fmt_list(items: list) -> str:
            if not items:
                return "  Tidak ada sinyal"
            return "\n".join([
                f"  • {a['ticker'].replace('.JK','')} — rating {a['rating']:.0f} @ {_rupiah(a['price'])}"
                for a in items
            ])

        message = (
            f"📋 <b>RINGKASAN SESI — {today}</b>\n"
            f"{'─' * 24}\n"
            f"🔭 Instrumen dipantau: {instruments_scanned}\n"
            f"📨 Total alert sesi ini: {len(alerts)}\n"
            f"\n"
            f"🟢 <b>Sinyal LONG ({len(long_alerts)}):</b>\n{_fmt_list(long_alerts)}\n"
            f"\n"
            f"🔴 <b>Sinyal SHORT ({len(short_alerts)}):</b>\n{_fmt_list(short_alerts)}\n"
            f"{'─' * 24}\n"
            f"<i>NEXUS Market Intelligence Engine</i>"
        )

        success = _send_with_retry(token, chat_id, message)
        if success:
            log.info("[DISPATCHER] Ringkasan sesi terkirim ✓")
        return success

    except Exception as exc:
        log.error(f"[DISPATCHER] Gagal kirim ringkasan sesi: {exc}")
        return False


def inter_message_pause() -> None:
    """Jeda antar pengiriman pesan berurutan — mencegah rate limit Telegram."""
    time.sleep(_INTER_MESSAGE_GAP)
