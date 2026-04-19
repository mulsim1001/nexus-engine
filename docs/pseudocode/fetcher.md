# Pseudocode & Penjelasan — `core/fetcher.py`

## Peran Modul

Fetcher adalah **jembatan antara dunia luar (internet) dan mesin analisa**. Tugasnya satu: ambil data harga saham yang valid, bersih, dan segar. Jika data tidak memenuhi syarat, fetcher menolaknya sebelum data itu sempat mempengaruhi sinyal.

---

## Penjelasan Dalam Bahasa Manusia

Bayangkan fetcher seperti seorang **petugas quality control di pintu masuk pabrik**. Setiap data yang datang dari luar harus melalui dia dulu.

Dia punya dua pemasok:
- **Pemasok A (yfinance):** Gratis, tidak terbatas, sudah terpercaya. Tapi kadang terlambat atau tidak responsif.
- **Pemasok B (Twelve Data):** Berbayar per pengiriman, tapi lebih handal. Hanya dipanggil kalau Pemasok A gagal.

Selain cek sumber data, dia juga cek **kesegaran data**: apakah data ini masih relevan? Kalau data sudah "basi" lebih dari 30 menit, dia tolak — lebih baik tidak punya data daripada punya data yang menyesatkan.

---

## Pseudocode

### Fungsi Utama: `fetch_instrument(ticker)`

```
FUNGSI fetch_instrument(ticker):

  MIN_CANDLES = 55
  MAX_AGE     = 30 menit

  # === SUMBER 1: yfinance ===
  data = ambil_dari_yfinance(ticker)

  JIKA data berhasil DAN jumlah baris >= MIN_CANDLES:
    JIKA candle_terakhir berumur <= MAX_AGE:
      LOG "berhasil dari yfinance"
      KEMBALIKAN data
    JIKA TIDAK:
      LOG "yfinance: data basi → eskalasi"

  # === SUMBER 2: Twelve Data (rescue) ===
  JIKA API_KEY tersedia:
    data = ambil_dari_twelvedata(ticker)

    JIKA data berhasil DAN jumlah baris >= MIN_CANDLES:
      JIKA candle_terakhir berumur <= MAX_AGE:
        LOG "berhasil dari Twelve Data (1 kredit terpakai)"
        KEMBALIKAN data
      JIKA TIDAK:
        LOG "Twelve Data: data juga basi → skip"

  # === SEMUA SUMBER GAGAL ===
  LOG ERROR "ticker dilewati — tidak ada sumber yang berhasil"
  KEMBALIKAN None
```

### Fungsi: `fetch_universe()`

```
FUNGSI fetch_universe():

  hasil = {}
  bagi LQ45_UNIVERSE menjadi batch ukuran 10

  UNTUK SETIAP batch:
    LOG "memproses batch ke-X"

    UNTUK SETIAP ticker dalam batch:
      data = fetch_instrument(ticker)
      JIKA data bukan None:
        hasil[ticker] = data

    JIKA bukan batch terakhir:
      TUNGGU 2 detik  ← mencegah rate limit

  LOG "selesai: X dari 45 instrumen berhasil"
  KEMBALIKAN hasil
```

### Fungsi: `_is_data_fresh(df, ticker)`

```
FUNGSI _is_data_fresh(df, ticker):

  candle_terakhir = df.index[-1]  ← timestamp baris paling bawah
  sekarang        = waktu_UTC_sekarang()

  umur_data = sekarang - candle_terakhir (dalam menit)

  JIKA umur_data > 30 menit:
    LOG WARNING "data {ticker} sudah {umur} menit — ditolak"
    KEMBALIKAN False

  KEMBALIKAN True
```

---

## Flowchart Cascade

```
ticker masuk
     │
     ▼
[yfinance] ────── gagal/basi ──────────────►[Twelve Data]
     │                                            │
  sukses                               sukses     │  gagal/basi
     │                                    │       │
     ▼                                    ▼       ▼
 validasi                            validasi    None
 freshness                           freshness   (ticker skip)
     │                                    │
  segar                               segar
     │                                    │
     ▼                                    ▼
DataFrame ✓                         DataFrame ✓
```

---

## Fungsi-Fungsi Private (Internal)

### `_pull_yfinance(ticker)`
Memanggil library `yfinance`, meminta 5 hari data interval 5 menit, membersihkan kolom yang tidak diperlukan, mengembalikan DataFrame OHLCV atau None kalau gagal.

### `_pull_twelvedata(ticker)`
Memanggil REST API Twelve Data dengan parameter `symbol`, `exchange=IDX`, `interval=5min`. Mengonversi respons JSON ke format DataFrame yang sama dengan yfinance. Mengonsumsi 1 kredit per panggilan.

### `get_last_price(df)`
Ambil satu angka: harga penutupan candle terakhir. `df["Close"].iloc[-1]`.

---

## Hal yang Perlu Diperhatikan

| Situasi | Perilaku |
|---|---|
| yfinance down total | Twelve Data dipakai (bila API key ada) |
| Twelve Data juga down | Ticker diskip siklus ini |
| Data berhasil tapi terlambat 35 menit | Ditolak, ticker diskip |
| Ticker baru listing (< 55 candle) | Ditolak karena data tidak cukup |
| Volume = 0 semua candle | Lulus fetcher, tapi FLOW layer akan menangani |
