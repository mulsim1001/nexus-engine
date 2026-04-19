# NEXUS — Panduan untuk Pemula
## Apa ini dan bagaimana cara kerjanya?

---

## Bayangkan begini...

Kamu punya asisten yang setiap 10 menit, sepanjang hari bursa, secara otomatis:
1. Mengecek harga 45 saham terbaik Indonesia (LQ45)
2. Menganalisa setiap saham dari 5 sudut pandang berbeda
3. Kalau ketemu saham yang "menarik" berdasarkan analisa tersebut, langsung kirim pesan ke Telegram kamu
4. Kalau tidak menarik, diam saja — tidak spam

Itulah NEXUS. Asisten analisa teknikal otomatis.

> **Penting:** NEXUS hanya menganalisa **pola harga dan data teknikal**. Dia tidak tahu berita perusahaan, laporan keuangan, atau isu politik. Anggap NEXUS sebagai salah satu pertimbangan, bukan keputusan final.

---

## Cara Kerjanya — Versi Sederhana

### Langkah 1: Ambil Data

Setiap 10 menit, NEXUS mengambil data harga saham dari internet (via Yahoo Finance). Kalau Yahoo Finance bermasalah untuk saham tertentu, dia otomatis coba sumber cadangan (Twelve Data).

Sebelum dianalisa, data dicek dulu: **apakah data ini baru?** Kalau data sudah lebih dari 30 menit, berarti mungkin sudah tidak relevan, jadi dibuang.

### Langkah 2: Analisa dari 5 Sudut Pandang

Setiap saham dinilai dari 5 aspek, masing-masing diberi bobot:

```
🔵 PULSE  — Apakah tren harganya naik atau turun?          (30%)
🟣 RADAR  — Apakah momentum belinya kuat?                  (25%)
🟡 FLOW   — Apakah ada banyak uang yang masuk?             (25%)
🟠 FORMATION — Apakah ada pola candlestick khusus?         (10%)
🔴 MACRO  — Apakah kondisi pasar keseluruhan (IHSG) baik? (10%)
```

Semua nilai digabung jadi satu **rating 0–100**.

### Langkah 3: Tentukan Sinyal

| Rating | Arti | Yang Terjadi |
|---|---|---|
| 80–100 | STRONG LONG / SHORT | Sinyal kuat — langsung dikirim |
| 65–79 | LONG / SHORT | Sinyal sedang — dikirim |
| Di bawah 65 | HOLD | Tidak ada sinyal — sistem diam |

### Langkah 4: Filter Anti-Spam

Sebelum pesan dikirim, ada 4 filter lagi:
1. **Cooldown 60 menit:** Saham yang sama tidak bisa kirim sinyal lagi dalam 60 menit
2. **Batas 8 sinyal/hari:** Lebih dari itu, sistem berhenti kirim walaupun ada sinyal bagus
3. **Konfirmasi 2 scan:** Sinyal harus muncul di 2 scan berturut-turut (20 menit) sebelum dikirim
4. **Cek database:** Kalau database tidak bisa diakses, sistem tidak kirim apapun (lebih aman)

### Langkah 5: Kirim Notifikasi

Kalau lolos semua filter, pesan dikirim ke Telegram. Kalau gagal kirim, dicoba ulang 3 kali sebelum menyerah.

---

## Apa itu Analisa Teknikal?

Analisa teknikal adalah cara menebak arah harga **hanya dari pola harga dan volume masa lalu**. Seperti membaca jejak kaki — dari pola jejak, kita tebak ke mana orang itu pergi.

NEXUS pakai beberapa "alat" analisa teknikal:

| Alat | Apa yang diukur |
|---|---|
| **EMA (Moving Average)** | Rata-rata harga bergerak — apakah tren naik atau turun? |
| **RSI** | Apakah saham sudah terlalu banyak dibeli/dijual? |
| **MACD** | Apakah momentum beli/jual sedang berubah arah? |
| **Stochastic** | Di mana posisi harga sekarang vs range harga belakangan ini? |
| **Volume** | Seberapa banyak saham yang diperdagangkan? Makin banyak = makin kuat sinyalnya |
| **Bollinger Bands** | Apakah harga terlalu "meregang" dari rata-ratanya? |
| **ADX** | Seberapa kuat trennya? Kalau lemah, sinyal diabaikan |

---

## Cara Membaca Notifikasi

Contoh pesan yang dikirim NEXUS ke Telegram:

```
🟢 STRONG LONG
────────────────────────
🏷 BBCA
💹 Harga: Rp 9.200
📊 Rating: 84/100 — Conviction: TINGGI

SINYAL:
  ▸ Harga di atas EMA20 — momentum positif jangka pendek
  ▸ Volume 2.4x baseline — arus dana di atas normal
  ▸ RSI 32 — zona jenuh jual, potensi pembalikan naik
  ▸ IHSG menguat 0.4% — sentimen pasar positif

  Pulse (Tren):     78/100
  Radar (Momentum): 82/100
  Flow  (Volume):   76/100

🎯 Target:    Rp 9.660 (+5.0%)
🛡 Guard:     Rp 8.975 (-2.5%)
⏱ Evaluasi:  10:20 WIB
────────────────────────
⚠ Analisa algoritmik — bukan saran investasi. Lakukan riset mandiri.
```

**Penjelasan setiap bagian:**

- **🟢 STRONG LONG** = Sinyal beli kuat
- **Rating 84/100** = Skor dari 5 analisa (semakin tinggi semakin kuat sinyalnya)
- **Conviction: TINGGI** = Sistem yakin dengan sinyal ini
- **SINYAL** = Alasan utama kenapa saham ini dipilih
- **Pulse/Radar/Flow** = Skor masing-masing aspek analisa
- **Target** = Harga yang ingin dicapai (+5%)
- **Guard** = Batas rugi yang disarankan (-2.5%)

---

## Setup Awal (Hanya Dilakukan Sekali)

### Yang Kamu Butuhkan:
1. Akun GitHub (gratis)
2. Akun Supabase (gratis) — untuk menyimpan data
3. Telegram Bot (gratis) — untuk terima notifikasi
4. Opsional: akun Twelve Data (gratis) — sumber data cadangan

### Langkah Setup:

**1. Buat Telegram Bot**
- Buka Telegram → cari `@BotFather`
- Ketik `/newbot` → ikuti instruksinya
- Simpan **TOKEN** yang diberikan

**2. Dapatkan Chat ID Grup**
- Buat grup Telegram
- Tambahkan bot ke grup
- Dapatkan Chat ID (bisa via `@userinfobot`)

**3. Setup Supabase**
- Daftar di [supabase.com](https://supabase.com)
- Buat project baru
- Buka SQL Editor → copy-paste isi file `supabase_setup.sql` → Run
- Simpan **Project URL** dan **Service Role Key** (bukan anon key!)

**4. Upload ke GitHub**
- Buat repository baru di GitHub (jadikan Public)
- Upload semua file NEXUS ke repository
- Buka Settings → Secrets → tambahkan:
  - `TELEGRAM_BOT_TOKEN` = token dari BotFather
  - `TELEGRAM_CHAT_ID` = ID grup Telegram
  - `SUPABASE_URL` = URL dari Supabase
  - `SUPABASE_KEY` = Service Role Key dari Supabase
  - `TWELVEDATA_API_KEY` = (opsional) key dari twelvedata.com

**5. Aktifkan GitHub Actions**
- Buka tab Actions di repository
- Enable workflows
- Sistem akan otomatis berjalan setiap 10 menit saat market buka

---

## Pertanyaan Umum

**Q: Berapa biaya operasional NEXUS?**  
A: Rp 0. Semua infrastruktur menggunakan free tier — GitHub Actions (unlimited untuk public repo), Supabase (500MB gratis), Telegram (gratis), yfinance (gratis).

**Q: Apakah sinyal NEXUS selalu benar?**  
A: Tidak ada sistem analisa teknikal yang selalu benar. NEXUS meningkatkan probabilitas menemukan setup yang bagus, tapi tetap ada risiko. Selalu gunakan stop loss.

**Q: Kenapa sinyalnya tidak langsung muncul setelah market buka?**  
A: NEXUS butuh 2 scan berturut-turut (20 menit) untuk mengkonfirmasi sinyal sebelum mengirimnya. Ini untuk menghindari sinyal palsu di awal sesi.

**Q: Apa bedanya STRONG LONG vs LONG?**  
A: STRONG LONG = rating 80–100 (keyakinan tinggi). LONG = rating 65–79 (keyakinan sedang). Keduanya adalah sinyal beli, tapi STRONG lebih kuat.

**Q: Kenapa ada hari di mana tidak ada sinyal sama sekali?**  
A: Bisa karena kondisi pasar sideways (tidak ada tren jelas), atau semua saham ratingnya di bawah 65. Ini normal — sistem lebih baik tidak kirim sinyal daripada kirim sinyal yang lemah.

**Q: Bagaimana kalau notifikasi tidak masuk?**  
A: Cek tab Actions di GitHub — apakah ada error? Pastikan Supabase tidak di-pause (free tier Supabase di-pause setelah 1 minggu tidak aktif).

---

## Peringatan Penting

> NEXUS adalah alat analisa teknikal otomatis, **bukan advisor investasi berlisensi**.  
> Semua keputusan beli/jual adalah tanggung jawab Anda sepenuhnya.  
> Selalu gunakan stop loss. Jangan investasikan uang yang tidak mampu Anda tanggung risikonya.
