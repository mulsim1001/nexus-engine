# Pseudocode & Penjelasan — `core/dispatcher.py`

## Peran Modul

Dispatcher adalah **kurir terakhir** dalam pipeline NEXUS. Dia menerima `AlertPacket` dari engine (hasil analisa yang sudah lolos semua filter) dan mengubahnya menjadi pesan yang bisa dibaca manusia, lalu mengirimkannya ke Telegram.

Dispatcher tidak membuat keputusan — dia hanya memformat dan mengirimkan keputusan yang sudah dibuat oleh engine dan run.py.

---

## Penjelasan Dalam Bahasa Manusia

Bayangkan dispatcher seperti **sekretaris yang membuat surat** dari hasil rapat. Rapat (engine) sudah memutuskan apa yang ingin disampaikan. Sekretaris mengambil keputusan itu, memformatnya menjadi surat yang rapi, dan mengirimkannya ke penerima (Telegram).

Kalau pengiriman pertama gagal, sekretaris mencoba lagi — tiga kali dengan jeda yang semakin lama. Kalau tiga kali tetap gagal, dia mencatat kegagalan itu tapi tidak menghentikan pekerjaan lainnya.

Di akhir hari, sekretaris juga membuat **ringkasan harian** yang mencantumkan semua sinyal yang sudah dikirim dan statistik sesi.

---

## Pseudocode

### Fungsi: `dispatch_alert(packet)`

```
FUNGSI dispatch_alert(packet):
  # Format pesan dari AlertPacket
  pesan = build_alert_message(packet)

  # Kirim ke Telegram (dengan retry)
  berhasil = _send_with_retry(pesan)

  JIKA berhasil:
    LOG INFO "alert terkirim: {ticker} {verdict}"
  JIKA TIDAK:
    LOG ERROR "alert gagal dikirim setelah 3 percobaan"

  KEMBALIKAN berhasil
```

### Fungsi: `_send_with_retry(text)`

```
FUNGSI _send_with_retry(text):
  MAX_RETRIES = 3
  DELAY_BASE  = 2 detik

  UNTUK attempt = 1 hingga MAX_RETRIES:
    response = panggil_telegram_api(
      method  = "sendMessage",
      chat_id = CHAT_ID,
      text    = text,
      format  = "HTML"
    )

    JIKA response.status == 200:
      KEMBALIKAN True

    JIKA response.status == 429:   ← rate limit
      retry_after = response.header["Retry-After"] atau 30 detik
      LOG WARNING "rate limited, tunggu {retry_after} detik"
      TUNGGU retry_after detik
      LANJUT ke percobaan berikutnya

    JIKA TIDAK:
      LOG WARNING "attempt {attempt} gagal: HTTP {status}"
      TUNGGU attempt × DELAY_BASE detik   ← backoff eksponensial: 2s, 4s, 6s

  KEMBALIKAN False
```

### Fungsi: `build_alert_message(packet)`

```
FUNGSI build_alert_message(packet):
  badge = emoji sesuai verdict:
    STRONG_LONG  → 🟢
    LONG         → 🟩
    STRONG_SHORT → 🔴
    SHORT        → 🟥
    HOLD         → ⚪ (tidak pernah dipanggil untuk HOLD)

  label        = verdict dalam format rapi ("STRONG LONG")
  conviction   = teks conviction ("TINGGI" / "SEDANG" / "LEMAH")
  top_notes    = 4 catatan pertama dari packet.notes
  notes_block  = setiap catatan diformat: "  ▸ catatan"

  # Format level harga
  JIKA verdict == "HOLD":
    up_str  = "—"
    grd_str = "—"
  JIKA TIDAK:
    up_str  = format_rupiah(packet.upside_level)
    grd_str = format_rupiah(packet.guard_level)

  pesan = """
  {badge} <b>{label}</b>
  ────────────────────────
  🏷 {ticker}
  💹 Harga: {harga}
  📊 Rating: {rating}/100 — Conviction: {conviction}

  SINYAL:
  {notes_block}

    Pulse (Tren):      {pulse_rating}/100
    Radar (Momentum):  {radar_rating}/100
    Flow  (Volume):    {flow_rating}/100

  🎯 Target:    {up_str}
  🛡 Guard:     {grd_str}
  ⏱ Evaluasi:  {waktu_sekarang} WIB
  ────────────────────────
  ⚠ Analisa algoritmik — bukan saran investasi.
  """

  KEMBALIKAN pesan
```

### Fungsi: `dispatch_session_summary(alerts, tickers_scanned)`

```
FUNGSI dispatch_session_summary(alerts, tickers_scanned):
  hitung:
    jumlah_long  = count(a for a in alerts if "LONG" in a.verdict)
    jumlah_short = count(a for a in alerts if "SHORT" in a.verdict)

  JIKA jumlah alerts == 0:
    isi = "Tidak ada sinyal yang memenuhi ambang konfluensi hari ini."
  JIKA TIDAK:
    daftar = setiap alert diformat satu baris:
              "{emoji} {ticker} {verdict} @ {harga} | {rating}/100"

  pesan = """
  📋 NEXUS — RINGKASAN SESI

  Instrumen dipindai   : {tickers_scanned}
  Total sinyal terkirim: {total}
  └ LONG  : {jumlah_long}
  └ SHORT : {jumlah_short}

  DAFTAR SINYAL:
  {daftar}

  Sesi ditutup: {waktu_WIB} WIB
  """

  KIRIM pesan (dengan retry)
```

### Fungsi: `inter_message_pause()`

```
FUNGSI inter_message_pause():
  TUNGGU 3 detik

  # Mencegah Telegram rate limit (max ~30 pesan/detik)
  # 3 detik memberi buffer aman
```

---

## Format Badge & Label

| Verdict | Badge | Label Tampilan |
|---|---|---|
| STRONG_LONG | 🟢 | STRONG LONG |
| LONG | 🟩 | LONG |
| STRONG_SHORT | 🔴 | STRONG SHORT |
| SHORT | 🟥 | SHORT |
| HOLD | ⚪ | HOLD (tidak pernah dispatch) |

---

## Hal yang Perlu Diperhatikan

| Situasi | Perilaku |
|---|---|
| Telegram API timeout | Dihitung sebagai gagal, retry |
| HTTP 429 (rate limited) | Baca `Retry-After` header, tunggu sesuai instruksi Telegram |
| HTTP 400 (bad request) | Kemungkinan format pesan salah, log error, tidak retry karena retry tidak akan membantu |
| Pesan terlalu panjang (> 4096 karakter) | Tidak mungkin terjadi — top_notes hanya 4 item |
| CHAT_ID tidak valid | Akan gagal di attempt pertama, dicatat error |
