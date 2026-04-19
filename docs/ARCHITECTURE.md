# NEXUS Market Intelligence Engine
## Arsitektur, Algoritma & Master Plan

**Versi:** 1.0.0  
**Tanggal:** April 2026  
**Klasifikasi:** Technical Reference

---

## 1. Gambaran Sistem

NEXUS adalah sistem analisa teknikal otomatis untuk pasar saham Indonesia (IDX) yang beroperasi sepenuhnya tanpa intervensi manusia selama jam sesi perdagangan. Sistem mengumpulkan data harga, menjalankan mesin evaluasi multi-layer, memfilter noise, dan mendistribusikan alert melalui Telegram.

```
┌─────────────────────────────────────────────────────────┐
│               NEXUS — Alur Eksekusi Lengkap             │
│                                                         │
│  GitHub Actions (cron */10 2-8 * * 1-5)                │
│          │                                              │
│          ▼                                              │
│  run.py ── cek jam sesi ── di luar jam? ──► EXIT        │
│          │                                              │
│          ▼                                              │
│  Ledger: cek Supabase ── tidak bisa konek? ──► ABORT   │
│          │                                              │
│          ▼                                              │
│  Fetcher: ambil IHSG + 45 saham LQ45                   │
│    └── cascade: yfinance → Twelve Data                  │
│    └── validasi freshness (max 30 menit)                │
│          │                                              │
│          ▼                                              │
│  Engine: evaluasi setiap instrumen                      │
│    └── PULSE  (tren)       × 30%                        │
│    └── RADAR  (momentum)   × 25%                        │
│    └── FLOW   (volume)     × 25%                        │
│    └── FORMATION (pola)    × 10%                        │
│    └── MACRO  (IHSG)       × 10%                        │
│    └── rating 0–100 → verdict                           │
│          │                                              │
│  Filter:                                                │
│    └── verdict == HOLD? ──────────────────► SKIP        │
│    └── cooldown aktif? ───────────────────► SKIP        │
│    └── batas harian tercapai? ────────────► SKIP        │
│    └── belum 2 scan konfirmasi? ──────────► PENDING     │
│          │                                              │
│          ▼                                              │
│  Dispatcher: kirim alert ke Telegram                    │
│    └── retry 3x dengan backoff eksponensial             │
│    └── jeda 3 detik antar pesan                         │
│          │                                              │
│          ▼                                              │
│  Ledger: catat alert ke Supabase                        │
│          │                                              │
│          ▼                                              │
│  Mendekati close? ──► kirim ringkasan sesi              │
└─────────────────────────────────────────────────────────┘
```

---

## 2. Arsitektur Komponen

### 2.1 Peta Modul

```
nexus-engine/
│
├── run.py                  ← Orchestrator (entry point)
│
├── core/
│   ├── fetcher.py          ← Pengambilan data (multi-source cascade)
│   ├── engine.py           ← Scoring engine (5 layer)
│   ├── dispatcher.py       ← Pengiriman alert (Telegram)
│   └── ledger.py           ← State management (Supabase)
│
├── config/
│   ├── universe.py         ← Daftar instrumen (LQ45 + benchmark)
│   └── params.py           ← Semua konstanta sistem
│
└── .github/workflows/
    └── pulse.yml           ← Scheduler GitHub Actions
```

### 2.2 Dependency Graph

```
run.py
  ├── core/fetcher.py
  │     ├── config/universe.py
  │     └── config/params.py
  ├── core/engine.py
  │     └── config/params.py
  ├── core/dispatcher.py
  │     └── core/engine.py (AlertPacket)
  └── core/ledger.py
        └── config/params.py (via os.environ)
```

Tidak ada circular dependency. Semua modul hanya mengimport ke bawah (leaf → config).

---

## 3. Algoritma Scoring Engine (5 Layer)

### 3.1 Formula Agregasi

```
RATING = (
    PULSE_SCORE     × 0.30  +
    RADAR_SCORE     × 0.25  +
    FLOW_SCORE      × 0.25  +
    FORMATION_SCORE × 0.10  +
    MACRO_SCORE     × 0.10
) × 100

Range output: 0.0 – 100.0
```

Setiap layer menghasilkan skor ternormalisasi dalam rentang `[0.0, 1.0]`:
- `0.5` = netral (tidak bullish, tidak bearish)
- `> 0.5` = condong bullish
- `< 0.5` = condong bearish

### 3.2 Layer 1 — PULSE (Bobot 30%)

**Tujuan:** Mendeteksi arah dan kekuatan tren dominan.

**Indikator:**
- EMA Fast (20 periode) vs harga terakhir
- EMA Fast vs EMA Mid (50 periode)
- EMA Mid vs EMA Slow (100 periode)
- ADX (14 periode) sebagai penguat/pelemah sinyal

**Mekanisme voting:**

```
raw_score = 0

if harga > EMA_Fast:
    raw_score += 1       # harga di atas MA pendek = positif
else:
    raw_score -= 1

if EMA_Fast > EMA_Mid:
    raw_score += 1       # MA pendek di atas MA menengah = tren naik
else:
    raw_score -= 1

if EMA_Mid > EMA_Slow:
    raw_score += 1       # MA menengah di atas MA lambat = struktur bullish
else:
    raw_score -= 1

if ADX > 25:
    # tren kuat, pertahankan skor
elif ADX < 15:
    raw_score = raw_score × 0.4   # pasar sideways, reduksi kepercayaan

normalized = (raw_score + 3) / 6   # mapping -3..+3 → 0..1
```

**Catatan:** EMA_SLOW = 100 dipilih secara sadar — pada data interval 5 menit, 100 candle ≈ 8 jam perdagangan (sekitar 2 hari). Ini merepresentasikan tren jangka menengah, bukan jangka panjang seperti MA200 pada grafik harian.

### 3.3 Layer 2 — RADAR (Bobot 25%)

**Tujuan:** Konsensus dari 4 oscillator momentum yang independen. Sinyal hanya diterima bila minimal 3 dari 4 oscillator sepakat.

**Indikator & voting:**

| Oscillator | Kondisi Bullish | Kondisi Bearish | Bobot Suara |
|---|---|---|---|
| RSI (14) | < 30 (oversold) | > 70 (overbought) | 1.0 |
| Stochastic (14,3,3) | < 20 + %K naik | > 80 + %K turun | 1.0 |
| MACD (12,26,9) | golden cross | death cross | 1.0 (0.5 bila tidak crossover) |
| CCI (20) | < -100 | > 100 | 1.0 |

**Penentuan skor:**

```
if bullish_votes >= 3:
    score = 0.5 + (bullish_votes / 4) × 0.5   # → 0.875 bila 4/4 setuju
elif bearish_votes >= 3:
    score = 0.5 - (bearish_votes / 4) × 0.5   # → 0.125 bila 4/4 setuju
else:
    score = 0.5   # konsensus tidak tercapai = netral
```

MACD diberi bobot parsial (0.5) untuk kondisi non-crossover agar tidak terlalu agresif.

### 3.4 Layer 3 — FLOW (Bobot 25%)

**Tujuan:** Validasi apakah pergerakan harga didukung arus dana nyata. Pergerakan tanpa volume adalah sinyal yang lemah.

**Indikator:**
- Volume Ratio = volume_sekarang / avg_volume_20_hari
- OBV (On-Balance Volume) vs MA-OBV 20 hari
- MFI (Money Flow Index, 14 periode)

**Mekanisme skor (berbeda dari layer lain — dapat menghasilkan nilai < 0.5):**

```
score = 0.5   # baseline

if volume_ratio >= 2.5:   score += 0.25   # lonjakan ekstrem
elif volume_ratio >= 1.5: score += 0.12   # di atas normal
elif volume_ratio < 0.7:  score -= 0.10   # minat rendah

if OBV > OBV_MA:  score += 0.12   # akumulasi
else:             score -= 0.12   # distribusi

if MFI < 20:  score += 0.12   # money flow oversold
elif MFI > 80: score -= 0.12   # money flow overbought

score = clamp(score, 0.0, 1.0)
```

Layer ini adalah satu-satunya yang dapat secara aktif **menurunkan** skor bila distribusi terdeteksi (skor < 0.5).

### 3.5 Layer 4 — FORMATION (Bobot 10%)

**Tujuan:** Deteksi pola candlestick dan struktur harga sebagai konfirmasi tambahan.

**Pola yang dideteksi:**

| Pola | Arah | Kondisi |
|---|---|---|
| Bollinger Band rebound | Bullish | harga ≤ lower band & harga sekarang > sebelumnya |
| Bollinger Band rejection | Bearish | harga ≥ upper band & harga sekarang < sebelumnya |
| Hammer | Bullish | lower shadow > 2× body, upper shadow < body |
| Shooting Star | Bearish | upper shadow > 2× body, lower shadow < body |
| Bullish Engulfing | Bullish | candle hijau mencakup penuh candle merah sebelumnya |
| Bearish Engulfing | Bearish | candle merah mencakup penuh candle hijau sebelumnya |

**Output:**

```
if bullish_patterns > bearish_patterns: return 0.8
elif bearish_patterns > bullish_patterns: return 0.2
else: return 0.5
```

### 3.6 Layer 5 — MACRO (Bobot 10%)

**Tujuan:** Konteks kondisi pasar keseluruhan melalui benchmark IHSG. Mencegah sinyal beli di tengah pasar yang crash.

```
perubahan_ihsg = (harga_sekarang - harga_sebelumnya) / harga_sebelumnya

if perubahan <= -2%: return 0.1   # mode defensif
elif perubahan <= -1%: return 0.3  # waspada
elif perubahan >= +1%: return 0.8  # sentimen positif
else: return 0.55                  # stabil
```

### 3.7 Tabel Verdict

| Rating | Verdict | Conviction | Aksi |
|---|---|---|---|
| 80–100 | STRONG_LONG / STRONG_SHORT | STRONG | Dispatch segera |
| 65–79 | LONG / SHORT | MODERATE | Dispatch dengan label moderate |
| < 65 | HOLD | WEAK | Tidak dikirim |

**Penentuan arah (LONG vs SHORT):** Jika rating ≥ threshold tapi `pulse_norm < 0.5` (tren turun dominan), verdict menjadi SHORT/STRONG_SHORT meskipun oscillator bullish. PULSE adalah penentu arah.

---

## 4. Sistem Filter Anti-Noise

### 4.1 Filter Berlapis

```
Alert hanya terkirim bila SEMUA kondisi berikut terpenuhi:

  [1] rating >= 65  (threshold minimum)
  [2] TIDAK dalam cooldown 60 menit untuk ticker yang sama
  [3] Total alert hari ini < 8
  [4] Sinyal muncul konsisten di 2 scan berturut (20 menit)
  [5] Supabase dapat dijangkau (fail-safe)
```

### 4.2 Sistem Konfirmasi 2 Scan

Sinyal pertama kali muncul → disimpan sebagai `pending_alert`.  
Scan berikutnya (10 menit kemudian):
- Jika sinyal yang sama masih muncul → dispatch
- Jika sinyal menghilang → pending kadaluarsa (30 menit) dan dihapus

Ini mengeliminasi false signal yang hanya muncul satu kali akibat noise pasar.

---

## 5. Strategi Multi-Source Data

### 5.1 Cascade Fetcher

```
Untuk setiap ticker:

  COBA yfinance:
    → berhasil & data cukup & segar (< 30 menit) → GUNAKAN
    → gagal / stale → eskalasi ke Twelve Data

  COBA Twelve Data (bila API key tersedia):
    → berhasil & segar → GUNAKAN (1 kredit terpakai)
    → gagal / stale → SKIP ticker ini

  Tidak ada sumber yang berhasil → ticker dilewati
```

### 5.2 Manajemen Kredit Twelve Data

- Mode normal (yfinance semua berhasil): **0 kredit/hari**
- Mode rescue (5 ticker yfinance gagal): **5 kredit/hari**
- Free tier limit: **800 kredit/hari**

Sistem dirancang agar kredit Twelve Data hanya terpakai saat benar-benar diperlukan, bukan sebagai sumber rutin.

### 5.3 Validasi Kesegaran Data

Setiap DataFrame yang berhasil diambil divalidasi:
- Cek timestamp candle terakhir
- Jika usia data > 30 menit → ditolak (dianggap tidak relevan)
- Ticker yang gagal validasi kesegaran akan dilewati sepenuhnya

---

## 6. Infrastruktur & Deployment

### 6.1 Stack

| Komponen | Teknologi | Biaya |
|---|---|---|
| Scheduler | GitHub Actions (public repo) | Gratis (unlimited menit) |
| State Storage | Supabase PostgreSQL | Gratis (500MB, 2GB bandwidth) |
| Data Primer | Yahoo Finance via yfinance | Gratis |
| Data Sekunder | Twelve Data API | Gratis (800 kredit/hari) |
| Notifikasi | Telegram Bot API | Gratis |

### 6.2 Estimasi Konsumsi GitHub Actions

- Siklus: setiap 10 menit, Senin–Jumat, 09:00–15:50 WIB
- Durasi per siklus: ~5-7 menit (fetch + analisa + dispatch)
- Siklus per hari: ~41
- Estimasi menit/bulan: ~41 × 6 menit × 21 hari = ~5.166 menit/bulan
- Public repo: **unlimited menit** → tidak ada masalah

### 6.3 Fail-Safe Architecture

```
Kondisi gagal → Perilaku sistem
─────────────────────────────────────────────
Supabase down saat startup       → ABORT seluruh siklus (sys.exit 1)
Supabase down saat cek cooldown  → SKIP ticker tersebut
yfinance gagal untuk 1 ticker    → Eskalasi ke Twelve Data
Twelve Data gagal                → SKIP ticker
Telegram gagal kirim             → Retry 3x, log error, lanjut
Data terlalu lama (> 30 menit)   → SKIP ticker
```

Filosofi: **lebih baik tidak mengirim sinyal daripada mengirim sinyal yang salah atau duplikat.**

---

## 7. Database Schema (Supabase)

```sql
-- alert_log: riwayat semua alert yang terkirim
ticker   TEXT        -- kode saham (contoh: BBCA.JK)
verdict  TEXT        -- STRONG_LONG / LONG / SHORT / STRONG_SHORT
rating   NUMERIC     -- 0.0–100.0
price    NUMERIC     -- harga saat alert dikirim
sent_at  TIMESTAMPTZ -- waktu pengiriman (UTC)

-- pending_alerts: sinyal menunggu konfirmasi scan kedua
ticker     TEXT
verdict    TEXT
rating     NUMERIC
created_at TIMESTAMPTZ  -- auto-expire setelah 30 menit
```

---

## 8. Master Plan Pengembangan

### Versi 1.0 (Sekarang) — Foundation
- [x] 5-layer scoring engine
- [x] Multi-source cascade (yfinance + Twelve Data)
- [x] Fail-safe ledger (Supabase)
- [x] Telegram dispatcher dengan retry
- [x] Konfirmasi 2-scan anti-noise
- [x] Validasi kesegaran data

### Versi 1.1 — Reliability
- [ ] Backtest module: evaluasi akurasi sinyal 6 bulan terakhir
- [ ] Monitoring run: notifikasi ke operator bila siklus gagal
- [ ] Supabase Keep Alive: cegah database di-pause oleh Supabase free tier
- [ ] Unit test untuk setiap layer scoring

### Versi 1.2 — Intelligence
- [ ] Adaptive threshold: naikkan threshold otomatis saat win rate < 50%
- [ ] Sektor rotation: deteksi sektor mana yang sedang outperform
- [ ] Gap analysis: deteksi dan evaluasi gap opening pagi hari

### Versi 2.0 — Platform
- [ ] Dashboard web (monitoring sinyal real-time)
- [ ] Win rate tracker (berapa % sinyal yang menguntungkan)
- [ ] Multi-universe: tambah saham Small Cap, Mid Cap selain LQ45
- [ ] Multiple output: WhatsApp, Discord selain Telegram
