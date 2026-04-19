"""
NEXUS — Ledger
Manajemen state antar run via Supabase.

Prinsip fail-safe: bila Supabase tidak dapat dijangkau,
seluruh siklus pengiriman DIBATALKAN — bukan dilonggarkan.
Lebih baik melewatkan satu sinyal daripada membanjiri pengguna
dengan duplikasi akibat cek cooldown yang tidak berfungsi.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import requests

log = logging.getLogger(__name__)

UTC = timezone.utc
WIB = timezone(timedelta(hours=7))

_SUPABASE_TIMEOUT = 10  # detik


def _credentials() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        raise EnvironmentError("SUPABASE_URL atau SUPABASE_KEY tidak ditemukan di environment")
    return url, key


def _auth_headers(key: str) -> dict:
    return {
        "apikey":        key,
        "Authorization": f"Bearer {key}",
        "Content-Type":  "application/json",
    }


def is_on_cooldown(ticker: str, verdict: str, cooldown_minutes: int) -> Optional[bool]:
    """
    Cek apakah alert untuk ticker ini masih dalam periode cooldown.

    Return:
      True  — masih cooldown, jangan kirim
      False — sudah lewat cooldown, boleh kirim
      None  — Supabase tidak bisa dijangkau (BATALKAN pengiriman)

    Perbedaan dari varian sebelumnya: return None (bukan False) saat gagal,
    agar orchestrator bisa membuat keputusan yang aman (fail-safe).
    """
    try:
        url, key = _credentials()
        cutoff = (datetime.now(UTC) - timedelta(minutes=cooldown_minutes)).isoformat()

        resp = requests.get(
            f"{url}/rest/v1/alert_log",
            headers=_auth_headers(key),
            params={
                "ticker":   f"eq.{ticker}",
                "verdict":  f"eq.{verdict}",
                "sent_at":  f"gte.{cutoff}",
                "select":   "id",
                "limit":    "1",
            },
            timeout=_SUPABASE_TIMEOUT,
        )
        resp.raise_for_status()
        on_cooldown = len(resp.json()) > 0

        if on_cooldown:
            log.info(f"[LEDGER] {ticker} ({verdict}) masih cooldown — skip")
        return on_cooldown

    except Exception as exc:
        log.error(f"[LEDGER] Tidak dapat cek cooldown {ticker}: {exc}")
        return None  # Fail-safe: kembalikan None, bukan False


def count_alerts_today() -> Optional[int]:
    """
    Hitung total alert yang sudah terkirim hari ini (zona WIB).
    Return None bila Supabase tidak dapat dijangkau.
    """
    try:
        url, key = _credentials()
        today = datetime.now(WIB).date().isoformat()

        resp = requests.get(
            f"{url}/rest/v1/alert_log",
            headers=_auth_headers(key),
            params={"sent_at": f"gte.{today}", "select": "id"},
            timeout=_SUPABASE_TIMEOUT,
        )
        resp.raise_for_status()
        count = len(resp.json())
        log.info(f"[LEDGER] Alert terkirim hari ini: {count}")
        return count

    except Exception as exc:
        log.warning(f"[LEDGER] Tidak dapat hitung alert hari ini: {exc}")
        return None


def record_alert(ticker: str, verdict: str, rating: float, price: float) -> bool:
    """
    Catat alert yang berhasil dikirim ke ledger Supabase.
    Return True bila berhasil, False bila gagal (tidak kritikal — log saja).
    """
    try:
        url, key = _credentials()
        resp = requests.post(
            f"{url}/rest/v1/alert_log",
            headers=_auth_headers(key),
            json={
                "ticker":  ticker,
                "verdict": verdict,
                "rating":  rating,
                "price":   price,
                "sent_at": datetime.now(UTC).isoformat(),
            },
            timeout=_SUPABASE_TIMEOUT,
        )
        resp.raise_for_status()
        log.info(f"[LEDGER] Alert {ticker} ({verdict}) dicatat")
        return True

    except Exception as exc:
        log.error(f"[LEDGER] Gagal catat alert {ticker}: {exc}")
        return False


def get_pending_count(ticker: str, verdict: str) -> int:
    """
    Cek berapa kali sinyal ini sudah muncul dalam 25 menit terakhir (pending confirmation).
    Digunakan untuk sistem konfirmasi multi-scan.
    Return 0 bila Supabase tidak bisa dijangkau (aman: pending dianggap belum ada).
    """
    try:
        url, key = _credentials()
        cutoff = (datetime.now(UTC) - timedelta(minutes=25)).isoformat()

        resp = requests.get(
            f"{url}/rest/v1/pending_alerts",
            headers=_auth_headers(key),
            params={
                "ticker":     f"eq.{ticker}",
                "verdict":    f"eq.{verdict}",
                "created_at": f"gte.{cutoff}",
                "select":     "id",
            },
            timeout=_SUPABASE_TIMEOUT,
        )
        resp.raise_for_status()
        return len(resp.json())

    except Exception as exc:
        log.warning(f"[LEDGER] Tidak dapat cek pending {ticker}: {exc}")
        return 0


def register_pending(ticker: str, verdict: str, rating: float) -> bool:
    """Simpan sinyal pending yang menunggu konfirmasi scan berikutnya."""
    try:
        url, key = _credentials()
        resp = requests.post(
            f"{url}/rest/v1/pending_alerts",
            headers=_auth_headers(key),
            json={
                "ticker":     ticker,
                "verdict":    verdict,
                "rating":     rating,
                "created_at": datetime.now(UTC).isoformat(),
            },
            timeout=_SUPABASE_TIMEOUT,
        )
        resp.raise_for_status()
        return True

    except Exception as exc:
        log.error(f"[LEDGER] Gagal simpan pending {ticker}: {exc}")
        return False


def purge_expired_pending(max_age_minutes: int = 30) -> None:
    """Bersihkan pending alert yang sudah kadaluarsa di awal setiap siklus run."""
    try:
        url, key = _credentials()
        cutoff = (datetime.now(UTC) - timedelta(minutes=max_age_minutes)).isoformat()

        resp = requests.delete(
            f"{url}/rest/v1/pending_alerts",
            headers=_auth_headers(key),
            params={"created_at": f"lt.{cutoff}"},
            timeout=_SUPABASE_TIMEOUT,
        )
        resp.raise_for_status()
        log.info(f"[LEDGER] Expired pending alerts dibersihkan (lebih dari {max_age_minutes} menit)")

    except Exception as exc:
        log.warning(f"[LEDGER] Gagal membersihkan pending: {exc}")


def get_all_alerts_today() -> list[dict]:
    """Ambil seluruh alert yang terkirim hari ini untuk ringkasan sesi."""
    try:
        url, key = _credentials()
        today = datetime.now(WIB).date().isoformat()

        resp = requests.get(
            f"{url}/rest/v1/alert_log",
            headers=_auth_headers(key),
            params={
                "sent_at": f"gte.{today}",
                "select":  "ticker,verdict,rating,price,sent_at",
                "order":   "sent_at.asc",
            },
            timeout=_SUPABASE_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    except Exception as exc:
        log.warning(f"[LEDGER] Gagal ambil ringkasan hari ini: {exc}")
        return []
