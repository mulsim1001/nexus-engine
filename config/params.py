# ============================================================
# NEXUS — Parameter Konfigurasi Engine
# Semua konstanta dan threshold dikelola di sini
# ============================================================

# --- Jam Operasional IDX (zona waktu WIB = UTC+7) ---
SESSION_OPEN_HOUR   = 9
SESSION_OPEN_MINUTE = 0
SESSION_CLOSE_HOUR  = 15
SESSION_CLOSE_MINUTE = 50   # Buffer 10 menit sebelum close resmi (16:00)

# --- Interval Polling ---
POLL_INTERVAL_MINUTES = 10

# ============================================================
# PULSE LAYER — Deteksi Arah Tren
# ============================================================
EMA_FAST   = 20     # EMA jangka pendek
EMA_MID    = 50     # EMA jangka menengah
EMA_SLOW   = 100    # EMA jangka panjang (disesuaikan dengan data intraday 5m)
                    # Catatan: 100 candle × 5 menit = ±8 jam trading (~2 hari)
                    # Ini representasi MA jangka menengah pada timeframe 5m

ADX_LOOKBACK      = 14
ADX_TRENDING      = 25   # ADX > 25 → tren sedang aktif
ADX_RANGING       = 15   # ADX < 15 → pasar sideways / konsolidasi

WEIGHT_PULSE = 0.30

# ============================================================
# RADAR LAYER — Konsensus Oscillator Momentum
# ============================================================
RSI_WINDOW    = 14
RSI_FLOOR     = 30      # Di bawah ini = jenuh jual
RSI_CEILING   = 70      # Di atas ini = jenuh beli

STOCH_PERIOD  = 14
STOCH_SMOOTH  = 3
STOCH_SIGNAL  = 3
STOCH_FLOOR   = 20
STOCH_CEILING = 80

MACD_SHORT    = 12
MACD_LONG     = 26
MACD_TRIGGER  = 9

CCI_WINDOW    = 20
CCI_FLOOR     = -100
CCI_CEILING   = 100

RADAR_MIN_VOTES = 3     # Minimal 3 dari 4 oscillator harus sepakat

WEIGHT_RADAR = 0.25

# ============================================================
# FLOW LAYER — Analisa Arus Dana & Volume
# ============================================================
FLOW_BASELINE_PERIOD  = 20      # Periode rata-rata volume referensi
FLOW_ELEVATED_RATIO   = 1.5     # Volume di atas ini dianggap signifikan
FLOW_SURGE_RATIO      = 2.5     # Volume di atas ini dianggap luar biasa
MFI_WINDOW            = 14
MFI_FLOOR             = 20
MFI_CEILING           = 80

WEIGHT_FLOW = 0.25

# ============================================================
# FORMATION LAYER — Pola Harga & Struktur Teknikal
# ============================================================
BB_WINDOW = 20      # Periode Bollinger Bands
BB_WIDTH  = 2.0     # Lebar deviasi standar

WEIGHT_FORMATION = 0.10

# ============================================================
# MACRO LAYER — Konteks Pasar (IHSG)
# ============================================================
BENCHMARK_SLIP_CAUTION  = -0.01    # -1%: mode waspada
BENCHMARK_SLIP_DEFENSE  = -0.02    # -2%: mode defensif penuh

WEIGHT_MACRO = 0.10

# ============================================================
# THRESHOLD SINYAL OUTPUT
# ============================================================
CONVICTION_HIGH     = 80    # >= 80 → STRONG signal → kirim segera
CONVICTION_MODERATE = 65    # >= 65 → signal reguler → kirim dengan label moderate
# Di bawah 65 → HOLD / tidak dikirim

# ============================================================
# FILTER ANTI-NOISE & SPAM
# ============================================================
COOLDOWN_PER_TICKER  = 60   # Menit minimum antara 2 sinyal untuk ticker yang sama
MAX_DAILY_ALERTS     = 8    # Batas maksimum alert per hari kalender
CONFIRM_ROUNDS       = 2    # Sinyal harus konsisten selama N scan sebelum dikirim

# ============================================================
# KALKULASI LEVEL OTOMATIS
# ============================================================
UPSIDE_TARGET_PCT  = 0.05    # Target profit untuk sinyal beli (5%)
DOWNSIDE_GUARD_PCT = 0.025   # Guard level untuk sinyal beli (2.5%)
SHORT_TARGET_PCT   = 0.05    # Target profit untuk sinyal jual (5%)
SHORT_GUARD_PCT    = 0.025   # Guard level untuk sinyal jual (2.5%)

# ============================================================
# KONFIGURASI PENGAMBILAN DATA
# ============================================================
# Catatan arsitektur (tidak diimport oleh kode — hanya dokumentasi inline):
# Sumber data primer  : yfinance (gratis, unlimited, cascade pertama)
# Sumber data sekunder: Twelve Data API (rescue, 1 kredit/ticker saat yfinance gagal)

DATA_LOOKBACK     = "5d"               # Rentang historis yang diambil
DATA_RESOLUTION   = "5m"              # Resolusi candle (5 menit)
FETCH_BATCH_SIZE  = 10                 # Ukuran batch per request
FETCH_BATCH_PAUSE = 2                  # Detik jeda antar batch
DATA_MAX_DELAY_MINUTES = 30            # Maksimum usia data yang masih diterima
MIN_CANDLES_REQUIRED   = 55            # Minimal candle agar analisa bermakna

TWELVEDATA_BASE_URL = "https://api.twelvedata.com/time_series"
TWELVEDATA_RESOLUTION = "5min"         # Format interval Twelve Data
TWELVEDATA_CANDLES    = 390            # ~5 hari × 78 candle/hari
