# Pseudocode & Penjelasan — `run.py`

## Peran Modul

`run.py` adalah **dirigen orkestra** — dia tidak memainkan instrumen apapun sendiri, tapi dia yang menentukan siapa bermain, kapan, dan dalam urutan apa. Semua modul lain (fetcher, engine, dispatcher, ledger) dipanggil oleh `run.py`.

---

## Penjelasan Dalam Bahasa Manusia

Bayangkan `run.py` seperti seorang **manajer shift** yang mengawasi seluruh operasi:

1. Pertama, dia cek **apakah sekarang jam kerja** (hari bursa? jam 09:00–15:50?)
2. Dia cek **apakah semua sistem online** (bisa konek ke database?)
3. Dia minta **fetcher** mengumpulkan data harga
4. Untuk setiap saham, dia minta **engine** mengevaluasi
5. Kalau engine menemukan sinyal, dia jalankan serangkaian **filter keamanan**
6. Kalau semua filter lolos, dia minta **dispatcher** mengirim notifikasi
7. Dia minta **ledger** mencatat semua yang terjadi
8. Mendekati tutup pasar, dia kirim **ringkasan harian**

---

## Pseudocode Lengkap

```
PROGRAM run.py

  setup_logging()

  # ──────────────────────────────────────────────
  # GATE 1: CEK JAM SESI
  # ──────────────────────────────────────────────
  sekarang = waktu_sekarang(timezone=WIB)

  JIKA sekarang.weekday() tidak dalam [Senin..Jumat]:
    LOG INFO "Hari libur — lewati"
    EXIT(0)

  JIKA sekarang.jam < SESSION_OPEN (09:00):
    LOG INFO "Sebelum jam buka — lewati"
    EXIT(0)

  JIKA sekarang.jam > SESSION_CLOSE (15:50):
    LOG INFO "Setelah jam tutup — lewati"
    EXIT(0)

  # ──────────────────────────────────────────────
  # GATE 2: VERIFIKASI KONEKSI DATABASE (FAIL-SAFE)
  # ──────────────────────────────────────────────
  total_alert_hari_ini = ledger.count_alerts_today()

  JIKA total_alert_hari_ini adalah None:
    LOG ERROR "Supabase tidak dapat dijangkau — batalkan siklus"
    EXIT(1)   ← GitHub Actions akan menandai run ini sebagai FAILED

  JIKA total_alert_hari_ini >= MAX_DAILY_ALERTS (8):
    LOG INFO "Batas harian tercapai — lewati"
    EXIT(0)

  # ──────────────────────────────────────────────
  # BERSIHKAN PENDING LAMA
  # ──────────────────────────────────────────────
  ledger.purge_expired_pending(max_age_minutes=30)

  # ──────────────────────────────────────────────
  # AMBIL DATA
  # ──────────────────────────────────────────────
  benchmark_df = fetcher.fetch_benchmark()   ← data IHSG

  JIKA benchmark_df adalah None:
    LOG WARNING "Data IHSG tidak tersedia — MACRO layer akan netral"
    # Tidak fatal: engine akan tangani benchmark=None dengan score=0.5

  universe_data = fetcher.fetch_universe()   ← data semua 45 saham LQ45
  # universe_data = {ticker: DataFrame, ...}

  JIKA universe_data kosong:
    LOG WARNING "Tidak ada data instrumen yang berhasil diambil"
    EXIT(0)

  # ──────────────────────────────────────────────
  # LOOP EVALUASI PER INSTRUMEN
  # ──────────────────────────────────────────────
  alerts_dispatched = []
  dispatched_this_cycle = 0

  UNTUK SETIAP ticker, df dalam universe_data:

    # === ANALISA ===
    packet = engine.evaluate(ticker, df, benchmark_df)

    JIKA packet adalah None:
      LANJUT ke ticker berikutnya   ← data tidak cukup

    JIKA packet.verdict == "HOLD":
      LANJUT ke ticker berikutnya   ← tidak ada sinyal

    # === FILTER COOLDOWN ===
    cooldown_status = ledger.is_on_cooldown(ticker, packet.verdict)

    JIKA cooldown_status adalah None:
      LOG WARNING "cooldown tidak terverifikasi — skip {ticker}"
      LANJUT ke ticker berikutnya

    JIKA cooldown_status == True:
      LOG DEBUG "{ticker} masih dalam cooldown"
      LANJUT ke ticker berikutnya

    # === FILTER BATAS HARIAN ===
    sisa_quota = MAX_DAILY_ALERTS - total_alert_hari_ini - dispatched_this_cycle

    JIKA sisa_quota <= 0:
      LOG INFO "Kuota harian habis — hentikan loop"
      BREAK

    # === FILTER KONFIRMASI 2-SCAN ===
    pending_count = ledger.get_pending_count(ticker, packet.verdict)

    JIKA pending_count < (CONFIRM_ROUNDS - 1):  # belum cukup konfirmasi
      LOG DEBUG "{ticker}: pending scan ke-{pending_count+1}"
      ledger.register_pending(ticker, packet.verdict, packet.rating)
      LANJUT ke ticker berikutnya

    # === SEMUA FILTER LOLOS → DISPATCH ===
    berhasil = dispatcher.dispatch_alert(packet)

    JIKA berhasil:
      ledger.record_alert(ticker, packet.verdict, packet.rating, packet.last_price)
      alerts_dispatched.append(packet)
      dispatched_this_cycle += 1
      dispatcher.inter_message_pause()   ← jeda 3 detik antar pesan

  # ──────────────────────────────────────────────
  # RINGKASAN SESI (mendekati tutup pasar)
  # ──────────────────────────────────────────────
  JIKA sekarang sudah melewati (SESSION_CLOSE - 10 menit):
    semua_alert_hari_ini = ledger.get_all_alerts_today()
    dispatcher.dispatch_session_summary(
      alerts  = semua_alert_hari_ini,
      scanned = len(universe_data)
    )

  LOG INFO "Siklus selesai — {dispatched_this_cycle} alert dikirim siklus ini"
  EXIT(0)
```

---

## Diagram Alur Keputusan Per Ticker

```
ticker masuk
     │
     ▼
engine.evaluate() ──→ None? ────────────────────────────────► SKIP
     │
     ▼
verdict == HOLD? ──────────────────────────────────────────► SKIP
     │
     ▼
is_on_cooldown()
  ├──→ None? (Supabase down)  ─────────────────────────────► SKIP
  ├──→ True? (masih cooldown) ─────────────────────────────► SKIP
  └──→ False → lanjut
     │
     ▼
kuota harian habis? ────────────────────────────────────────► BREAK
     │
     ▼
pending_count < 1?
  ├──→ Ya: register_pending() ─────────────────────────────► SKIP
  └──→ Tidak (sudah 1 pending): lanjut
     │
     ▼
dispatch_alert()
     │
     ├──→ berhasil:
     │     record_alert()
     │     inter_message_pause()
     │     alerts_dispatched.append(packet)
     │
     └──→ gagal: log error, lanjut ke ticker berikutnya
```

---

## Nilai Exit Code

| Exit Code | Artinya | Akibat di GitHub Actions |
|---|---|---|
| `0` | Siklus selesai normal | Run hijau ✓ |
| `1` | Abort karena Supabase tidak dapat dijangkau | Run merah ✗ |

Exit code `1` hanya digunakan ketika database tidak dapat diverifikasi di awal siklus. Ini menjamin bahwa operator mendapat notifikasi (via GitHub Actions email/alert) ketika infrastruktur bermasalah.

---

## Hal yang Perlu Diperhatikan

| Situasi | Perilaku `run.py` |
|---|---|
| `count_alerts_today()` = None | EXIT(1) — abort seluruh siklus |
| `count_alerts_today()` = 8 | EXIT(0) — batas harian, normal |
| `universe_data` kosong | EXIT(0) — log warning, tidak error |
| `benchmark_df` = None | Teruskan tanpa benchmark — engine netral di MACRO |
| `dispatch_alert()` gagal | Log error, lanjut ke ticker berikutnya |
| Lebih dari 8 sinyal dalam satu siklus | Hanya 8 pertama yang dikirim |
