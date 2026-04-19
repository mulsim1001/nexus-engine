# NEXUS Market Intelligence Engine

Sistem analisa teknikal otomatis untuk pasar saham Indonesia (IDX) — khusus instrumen **LQ45**.

Berjalan sepenuhnya gratis menggunakan GitHub Actions, Supabase, dan Telegram.

---

## Cara Kerja

Setiap **10 menit** selama jam bursa (Senin–Jumat, 09:00–15:50 WIB), sistem:

1. Mengambil data harga 45 saham LQ45 dari Yahoo Finance
2. Mengevaluasi setiap instrumen dengan **5-layer scoring engine**
3. Mengirim sinyal ke Telegram bila rating ≥ 65/100 dan terkonfirmasi 2 scan berturut

```
PULSE     (30%) — deteksi tren via EMA 20/50/100 + ADX
RADAR     (25%) — konsensus RSI, Stochastic, MACD, CCI
FLOW      (25%) — arus dana via volume ratio, OBV, MFI
FORMATION (10%) — pola candlestick & Bollinger Band
MACRO     (10%) — sentimen pasar via IHSG benchmark
```

---

## Stack

| Komponen | Teknologi | Biaya |
|---|---|---|
| Scheduler | GitHub Actions (public repo) | Gratis |
| Database state | Supabase PostgreSQL | Gratis |
| Data primer | Yahoo Finance (yfinance) | Gratis |
| Data cadangan | Twelve Data API | Gratis (800 kredit/hari) |
| Notifikasi | Telegram Bot API | Gratis |

---

## Struktur Project

```
nexus-engine/
├── run.py                    ← entry point (orchestrator)
├── dry_run.py                ← simulator offline untuk testing
├── requirements.txt
├── supabase_setup.sql        ← script setup database
├── core/
│   ├── engine.py             ← 5-layer scoring engine
│   ├── fetcher.py            ← multi-source data cascade
│   ├── dispatcher.py         ← Telegram alert sender
│   └── ledger.py             ← Supabase state manager
├── config/
│   ├── params.py             ← semua konstanta & threshold
│   └── universe.py           ← daftar 45 saham LQ45
├── .github/workflows/
│   └── pulse.yml             ← GitHub Actions scheduler
└── docs/
    ├── PANDUAN_SETUP_GITHUB.md  ← panduan setup lengkap
    ├── ARCHITECTURE.md          ← arsitektur & master plan
    ├── README_pemula.md         ← panduan untuk pemula
    └── pseudocode/              ← penjelasan tiap modul
```

---

## Quick Start

Lihat panduan setup lengkap di [`docs/PANDUAN_SETUP_GITHUB.md`](docs/PANDUAN_SETUP_GITHUB.md).

Ringkasan:
1. Buat Telegram Bot → dapatkan `TOKEN` dan `CHAT_ID`
2. Buat project Supabase → jalankan `supabase_setup.sql` → ambil URL dan Service Key
3. Fork/clone repo ini → tambahkan 4 GitHub Secrets
4. Enable GitHub Actions → jalankan workflow manual pertama kali

### Test Offline (tanpa server)

```bash
pip install pandas numpy
python dry_run.py
```

---

## Roadmap

- [ ] Backtest module (evaluasi akurasi sinyal historis)
- [ ] Web dashboard monitoring real-time
- [ ] Adaptive threshold berdasarkan win rate
- [ ] Multi-universe (Small Cap, Mid Cap)
- [ ] Multi-output (Discord, WhatsApp)

---

## Kontribusi

Project ini terbuka untuk kolaborasi. Area yang paling dibutuhkan:
- **Backtest engine** — validasi akurasi sinyal secara historis
- **Web dashboard** — visualisasi sinyal dan statistik
- **Strategi tambahan** — layer atau indikator baru

---

> ⚠️ *Sistem ini adalah alat analisa teknikal, bukan saran investasi. Semua keputusan investasi adalah tanggung jawab pengguna sepenuhnya.*
