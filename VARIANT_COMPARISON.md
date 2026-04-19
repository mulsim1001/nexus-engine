# Perbandingan: IDX Trading System (X) vs NEXUS Engine

## Identitas Sistem

| Aspek | Varian Lama (X) | NEXUS Engine |
|---|---|---|
| Nama proyek | IDX Trading Intelligence System | NEXUS Market Intelligence Engine |
| Entry point | `main.py` | `run.py` |
| Folder modul | `src/` | `core/` |
| Folder konfigurasi | `config/` | `config/` (sama, isi berbeda) |
| GitHub Actions | `scan.yml` | `pulse.yml` |
| Nama job | `scan` | `pulse` |

---

## Pemetaan File & Penamaan Modul

| Peran | Varian Lama | NEXUS |
|---|---|---|
| Pengambilan data | `src/scanner.py` | `core/fetcher.py` |
| Mesin analisa | `src/analyzer.py` | `core/engine.py` |
| Pengirim notifikasi | `src/notifier.py` | `core/dispatcher.py` |
| Manajemen state | `src/storage.py` | `core/ledger.py` |
| Daftar saham | `config/watchlist.py` | `config/universe.py` |
| Parameter sistem | `config/settings.py` | `config/params.py` |
| Setup database | `supabase_setup.sql` | `supabase_setup.sql` |

---

## Pemetaan Terminologi Algoritma

| Konsep | Varian Lama | NEXUS |
|---|---|---|
| Nama Layer 1 | Trend Detection | PULSE Layer |
| Nama Layer 2 | Momentum & Oscillator | RADAR Layer |
| Nama Layer 3 | Volume Analysis | FLOW Layer |
| Nama Layer 4 | Price Action & Pattern | FORMATION Layer |
| Nama Layer 5 | Market Context | MACRO Layer |
| Indikator tren | MA20/MA50/MA200 (SMA) | EMA Fast/Mid/Slow (EMA) |
| Output sinyal | STRONG_BUY / BUY / NEUTRAL / SELL / STRONG_SELL | STRONG_LONG / LONG / HOLD / SHORT / STRONG_SHORT |
| Container hasil analisa | `SignalResult` | `AlertPacket` |
| Tingkat keyakinan | HIGH / MODERATE / LOW | STRONG / MODERATE / WEAK |
| Target profit | `target_price` | `upside_level` |
| Stop loss | `stop_loss` | `guard_level` |
| Skor akhir | `score` | `rating` |
| Fungsi analisa utama | `analyze()` | `evaluate()` |
| Pengirim sinyal | `send_signal()` | `dispatch_alert()` |
| Cek cooldown | `was_signal_recently_sent()` | `is_on_cooldown()` |
| Catat sinyal terkirim | `save_signal()` | `record_alert()` |
| Tabel DB sinyal | `signal_log` | `alert_log` |
| Tabel DB pending | `pending_signals` | `pending_alerts` |
| Fetch semua saham | `fetch_all_stocks()` | `fetch_universe()` |
| Fetch benchmark | `fetch_ihsg()` | `fetch_benchmark()` |

---

## Perbaikan Teknis yang Diimplementasikan di NEXUS

### 1. Multi-Source Data (Fitur Baru)
- **Varian Lama:** 100% bergantung pada yfinance satu sumber
- **NEXUS:** Cascade `yfinance → Twelve Data`
  - yfinance: primary, gratis, unlimited
  - Twelve Data: rescue hanya saat yfinance gagal (hemat kredit)
  - Kredit Twelve Data hanya terpakai bila yfinance benar-benar tidak bisa melayani ticker tertentu

### 2. Validasi Kesegaran Data (Bug Fix)
- **Varian Lama:** Tidak ada pengecekan kapan data terakhir diperbarui
- **NEXUS:** Setiap DataFrame divalidasi via `_is_data_fresh()` — data lebih dari 30 menit ditolak

### 3. Fail-Safe Ledger (Bug Fix Kritis)
- **Varian Lama:** `return False` saat Supabase down → sinyal terkirim tanpa cek cooldown
- **NEXUS:** `return None` saat Supabase down → orchestrator membatalkan dispatch seluruh siklus (`sys.exit(1)`)

### 4. Retry dengan Backoff Eksponensial (Fitur Baru)
- **Varian Lama:** Satu kali request, langsung gagal bila error
- **NEXUS:** Retry hingga 3 kali dengan jeda `2s → 4s → 6s`
- Handle khusus untuk HTTP 429 (rate limit Telegram) dengan membaca header `Retry-After`

### 5. Concurrency Control GitHub Actions (Bug Fix)
- **Varian Lama:** Tidak ada, bisa overlap run
- **NEXUS:** `concurrency.group: nexus-market-pulse` — siklus baru dibatalkan bila yang lama masih berjalan

### 6. EMA Bukan SMA (Perbaikan Algoritma)
- **Varian Lama:** MA20/MA50/MA200 menggunakan Simple Moving Average
- **NEXUS:** EMA Fast/Mid/Slow menggunakan Exponential MA — lebih responsif terhadap pergerakan terkini

### 7. EMA_SLOW Disesuaikan (Perbaikan Semantik)
- **Varian Lama:** MA_LONG = 200 → pada 5m candle = hanya 16 jam data (menyesatkan sebagai "MA jangka panjang")
- **NEXUS:** EMA_SLOW = 100 → dengan komentar eksplisit yang menjelaskan representasi sebenarnya

### 8. Skor FLOW Dapat Negatif (Perbaikan Algoritma)
- **Varian Lama:** Layer Volume hanya menghasilkan skor 0.0–1.0, tidak bisa menurunkan skor final
- **NEXUS:** Layer FLOW bisa menurunkan skor saat distribusi volume terdeteksi (score dapat < 0.5)

### 9. Seleksi Catatan Berdasarkan Relevansi (Perbaikan UX)
- **Varian Lama:** `reasons[:4]` — ambil 4 pertama tanpa pertimbangan relevansi
- **NEXUS:** `_select_top_notes()` — prioritas catatan berdasarkan bobot layer (Pulse → Flow → Radar → Formation → Macro)

### 10. Delay Antar Pesan (Bug Fix)
- **Varian Lama:** Tidak ada delay antar pengiriman pesan
- **NEXUS:** `inter_message_pause()` — jeda 3 detik antar dispatch untuk mencegah rate limit Telegram

---

## Struktur Folder Lengkap

```
nexus-engine/
├── .github/
│   └── workflows/
│       └── pulse.yml              # GitHub Actions — polling setiap 10 menit
├── core/
│   ├── __init__.py
│   ├── fetcher.py                 # Multi-source data cascade (yfinance + Twelve Data)
│   ├── engine.py                  # 5-layer scoring engine (PULSE/RADAR/FLOW/FORMATION/MACRO)
│   ├── dispatcher.py              # Telegram dispatch dengan retry & rate limiting
│   └── ledger.py                  # State management fail-safe via Supabase
├── config/
│   ├── __init__.py
│   ├── universe.py                # LQ45 instrument list + benchmark
│   └── params.py                  # Semua konstanta & threshold
├── supabase_setup.sql             # Schema database (jalankan sekali)
├── run.py                         # Entry point utama
├── requirements.txt
└── VARIANT_COMPARISON.md          # Dokumen ini
```

---

## GitHub Secrets yang Diperlukan

| Secret | Keterangan |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token bot dari @BotFather |
| `TELEGRAM_CHAT_ID` | ID grup/channel tujuan |
| `SUPABASE_URL` | URL project Supabase |
| `SUPABASE_KEY` | Service Role Key Supabase (bukan anon key) |
| `TWELVEDATA_API_KEY` | API key dari twelvedata.com (opsional — fallback aktif hanya bila ada) |
