# Pseudocode & Penjelasan — `core/engine.py`

## Peran Modul

Engine adalah **otak sistem**. Dia menerima data harga mentah dan mengubahnya menjadi satu angka (rating 0–100) yang merepresentasikan seberapa kuat sinyal untuk instrumen tersebut.

Engine tidak tahu apakah sinyal akan dikirim atau tidak — itu urusan `run.py`. Engine hanya bertugas mengevaluasi secara objektif.

---

## Penjelasan Dalam Bahasa Manusia

Bayangkan 5 analis independen yang masing-masing punya keahlian berbeda:

- **Analis PULSE** ahli dalam membaca tren jangka panjang
- **Analis RADAR** ahli dalam oscillator dan momentum
- **Analis FLOW** ahli dalam analisa arus dana dan volume
- **Analis FORMATION** ahli dalam membaca pola candlestick
- **Analis MACRO** ahli dalam kondisi pasar makro (IHSG)

Setiap analis memberikan penilaian 0–100. Penilaian akhir adalah rata-rata tertimbang — analis yang lebih penting mendapat bobot lebih besar.

**Keputusan arah** (beli vs jual) ditentukan oleh Analis PULSE. Kalau PULSE bilang tren turun tapi rating keseluruhan tinggi → sinyal SHORT, bukan LONG.

---

## Pseudocode

### Fungsi Utama: `evaluate(ticker, df, benchmark_df)`

```
FUNGSI evaluate(ticker, df, benchmark_df):

  # Guard: data minimal 55 candle
  JIKA df adalah None ATAU len(df) < 55:
    LOG WARNING "data tidak cukup"
    KEMBALIKAN None

  # Jalankan 5 layer
  pulse_score, pulse_notes, adx  = _compute_pulse(df)
  radar_score, radar_notes, data = _compute_radar(df)
  flow_score,  flow_notes, ratio = _compute_flow(df)
  form_score,  form_notes        = _compute_formation(df)
  macro_score, macro_notes       = _compute_macro(benchmark_df)

  # Agregasi tertimbang
  rating = (
    pulse_score × 0.30  +
    radar_score × 0.25  +
    flow_score  × 0.25  +
    form_score  × 0.10  +
    macro_score × 0.10
  ) × 100

  # Tentukan verdict
  JIKA rating >= 80:
    JIKA pulse_score > 0.5: verdict = "STRONG_LONG"
    JIKA TIDAK:             verdict = "STRONG_SHORT"
    conviction = "STRONG"

  JIKA TIDAK JIKA rating >= 65:
    JIKA pulse_score > 0.5: verdict = "LONG"
    JIKA TIDAK:             verdict = "SHORT"
    conviction = "MODERATE"

  JIKA TIDAK:
    verdict    = "HOLD"
    conviction = "WEAK"

  # Kalkulasi level otomatis
  JIKA verdict mengandung "LONG":
    target = harga × 1.05    ← +5%
    guard  = harga × 0.975   ← -2.5%
  JIKA verdict mengandung "SHORT":
    target = harga × 0.95    ← -5%
    guard  = harga × 1.025   ← +2.5%

  # Susun catatan (urutan prioritas: PULSE → FLOW → RADAR → FORMATION → MACRO)
  catatan = pulse_notes + flow_notes + radar_notes + form_notes + macro_notes

  KEMBALIKAN AlertPacket(ticker, rating, verdict, target, guard, catatan, ...)
```

---

### Layer 1: `_compute_pulse(df)` — Deteksi Tren

```
FUNGSI _compute_pulse(df):
  Hitung EMA20, EMA50, EMA100 dari kolom Close

  skor_mentah = 0

  JIKA harga_terakhir > EMA20: skor_mentah += 1
  JIKA TIDAK:                  skor_mentah -= 1

  JIKA EMA20 > EMA50: skor_mentah += 1
  JIKA TIDAK:         skor_mentah -= 1

  JIKA EMA50 > EMA100: skor_mentah += 1
  JIKA TIDAK:          skor_mentah -= 1

  Hitung ADX (kekuatan tren, 14 periode)

  JIKA ADX > 25:
    tambahkan catatan "tren kuat"
  JIKA ADX < 15:
    skor_mentah = skor_mentah × 0.4  ← pasar sideways, kurangi kepercayaan
    tambahkan catatan "pasar konsolidasi"

  # Normalisasi -3..+3 → 0..1
  normalized = (skor_mentah + 3) / 6

  KEMBALIKAN (normalized, catatan, adx_value)
```

**Intuitif:** Makin banyak EMA yang "berurutan ke atas", makin bullish. ADX rendah = tren tidak valid, skor dikempiskan.

---

### Layer 2: `_compute_radar(df)` — Konsensus Oscillator

```
FUNGSI _compute_radar(df):
  bullish_votes = 0
  bearish_votes = 0

  # RSI
  rsi = hitung_RSI(14 periode)
  JIKA rsi < 30: bullish_votes += 1  ← oversold
  JIKA rsi > 70: bearish_votes += 1  ← overbought

  # Stochastic
  (stoch_k, stoch_d) = hitung_stochastic(14,3,3)
  JIKA stoch_k < 20 DAN stoch_k > stoch_d: bullish_votes += 1
  JIKA stoch_k > 80 DAN stoch_k < stoch_d: bearish_votes += 1

  # MACD (satu pass, tidak duplikasi komputasi)
  (line, signal, delta, delta_prev) = hitung_macd(12,26,9)
  JIKA delta > 0 DAN delta_prev <= 0: bullish_votes += 1.0   ← golden cross
  JIKA delta < 0 DAN delta_prev >= 0: bearish_votes += 1.0   ← death cross
  JIKA TIDAK JIKA delta > 0:          bullish_votes += 0.5   ← positif tapi tidak crossover
  JIKA TIDAK JIKA delta < 0:          bearish_votes += 0.5   ← negatif tapi tidak crossover

  # CCI
  cci = hitung_CCI(20 periode)
  JIKA cci < -100: bullish_votes += 1
  JIKA cci > 100:  bearish_votes += 1

  # Evaluasi konsensus (minimal 3 dari 4 harus setuju)
  JIKA bullish_votes >= 3:
    score = 0.5 + (bullish_votes / 4) × 0.5
  JIKA TIDAK JIKA bearish_votes >= 3:
    score = 0.5 - (bearish_votes / 4) × 0.5
  JIKA TIDAK:
    score = 0.5  ← tidak ada konsensus = netral

  KEMBALIKAN (score, catatan, {rsi, macd_delta, ...})
```

---

### Layer 3: `_compute_flow(df)` — Arus Dana

```
FUNGSI _compute_flow(df):
  JIKA volume semua nol: KEMBALIKAN (0.5, "tidak ada data volume", 0)

  avg_volume   = rata-rata volume 20 hari terakhir
  cur_volume   = volume candle terakhir
  volume_ratio = cur_volume / avg_volume

  score = 0.5  ← baseline

  # Kontribusi volume ratio
  JIKA volume_ratio >= 2.5: score += 0.25   ← lonjakan luar biasa
  JIKA volume_ratio >= 1.5: score += 0.12   ← di atas normal
  JIKA volume_ratio <  0.7: score -= 0.10   ← minat rendah

  # OBV (akumulasi vs distribusi)
  obv    = hitung_OBV()
  obv_ma = rata-rata OBV 20 hari
  JIKA obv > obv_ma: score += 0.12   ← akumulasi
  JIKA TIDAK:        score -= 0.12   ← distribusi

  # MFI (Money Flow Index)
  mfi = hitung_MFI(14 periode)
  JIKA mfi < 20: score += 0.12   ← oversold money flow
  JIKA mfi > 80: score -= 0.12   ← overbought money flow

  score = clamp(score, 0.0, 1.0)
  KEMBALIKAN (score, catatan, volume_ratio)
```

**Unik:** Layer ini adalah satu-satunya yang bisa menghasilkan skor < 0.5 secara aktif — artinya distribusi volume bisa menurunkan rating keseluruhan.

---

### Layer 4: `_compute_formation(df)` — Pola Harga

```
FUNGSI _compute_formation(df):
  bullish_count = 0
  bearish_count = 0

  # Bollinger Bands
  (upper, lower, mid) = hitung_bollinger(20 periode, 2 std)
  JIKA harga <= lower DAN harga_sekarang > harga_sebelumnya:
    bullish_count += 1  ← rebound dari bawah

  JIKA harga >= upper DAN harga_sekarang < harga_sebelumnya:
    bearish_count += 1  ← penolakan dari atas

  # Candlestick patterns (candle terakhir)
  JIKA is_hammer(open, high, low, close):       bullish_count += 1
  JIKA is_shooting_star(open, high, low, close): bearish_count += 1

  # Engulfing (butuh 2 candle terakhir)
  JIKA is_bullish_engulf(candle_sebelumnya, candle_terakhir): bullish_count += 1
  JIKA is_bearish_engulf(candle_sebelumnya, candle_terakhir): bearish_count += 1

  JIKA bullish_count > bearish_count: KEMBALIKAN (0.8, catatan)
  JIKA bearish_count > bullish_count: KEMBALIKAN (0.2, catatan)
  KEMBALIKAN (0.5, catatan)  ← seri atau tidak ada pola
```

**Cara cek Hammer:**
```
body          = |close - open|
lower_shadow  = min(open, close) - low
upper_shadow  = high - max(open, close)

Hammer JIKA: lower_shadow > 2 × body DAN upper_shadow < body DAN body > 0
```

---

### Layer 5: `_compute_macro(benchmark_df)` — Konteks IHSG

```
FUNGSI _compute_macro(benchmark_df):
  JIKA benchmark_df adalah None: KEMBALIKAN (0.5, "data tidak tersedia")

  perubahan = (ihsg_sekarang - ihsg_sebelumnya) / ihsg_sebelumnya

  JIKA perubahan <= -2%: KEMBALIKAN (0.10, "mode defensif")
  JIKA perubahan <= -1%: KEMBALIKAN (0.30, "waspada")
  JIKA perubahan >= +1%: KEMBALIKAN (0.80, "sentimen positif")
  KEMBALIKAN (0.55, "stabil")
```

---

## AlertPacket — Objek Hasil

```
AlertPacket:
  ticker        → "BBCA.JK"
  rating        → 84.2        (skor 0-100)
  verdict       → "STRONG_LONG"
  last_price    → 9200.0
  upside_level  → 9660.0      (+5%)
  guard_level   → 8975.0      (-2.5%)
  conviction    → "STRONG"
  pulse_rating  → 78.0        (sub-skor PULSE)
  radar_rating  → 87.5        (sub-skor RADAR)
  flow_rating   → 70.0        (sub-skor FLOW)
  formation_rating → 80.0
  macro_rating  → 80.0
  notes         → ["Harga di atas EMA20...", "Volume 2.4x...", ...]
  rsi_value     → 32.1
  macd_delta    → 0.0045
  flow_ratio    → 2.4
  adx_value     → 28.3
```
