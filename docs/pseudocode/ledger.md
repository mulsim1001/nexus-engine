# Pseudocode & Penjelasan — `core/ledger.py`

## Peran Modul

Ledger adalah **memori jangka pendek sistem** — jembatan antara NEXUS dan database Supabase. Dia menyimpan dan membaca dua jenis data:

1. **`alert_log`** — Catatan permanen semua alert yang sudah terkirim (dipakai untuk cooldown dan batas harian)
2. **`pending_alerts`** — Catatan sementara sinyal yang menunggu konfirmasi scan kedua

---

## Penjelasan Dalam Bahasa Manusia

Bayangkan ledger seperti **buku catatan + arsip** yang dijaga oleh penjaga pintu gerbang. Setiap kali ada sinyal yang ingin "keluar" (dispatch), penjaga ini dicek dulu:

- "Apakah saham ini sudah pernah diberi sinyal dalam 60 menit terakhir?" → cek cooldown
- "Sudah berapa sinyal yang keluar hari ini?" → cek batas harian

Kalau saham ini baru saja diberi sinyal (masih dalam cooldown), penjaga blokir. Kalau sudah 8 sinyal hari ini, penjaga tutup pintu.

Ketika sinyal pertama kali muncul, penjaga juga menyimpan "tiket tunggu" (pending alert). Baru setelah scan kedua, tiket itu divalidasi dan pintu dibuka.

**Prinsip keamanan:** Kalau penjaga ini tidak bisa dihubungi (Supabase down), dia mengembalikan `None` — bukan "boleh lewat". Keputusan final ada di `run.py` yang memperlakukan `None` sebagai "stop, jangan kirim".

---

## Pseudocode

### Fungsi: `is_on_cooldown(ticker, verdict, minutes)`

```
FUNGSI is_on_cooldown(ticker, verdict, minutes=60):
  batas_waktu = sekarang_UTC - minutes menit

  COBA:
    query ke Supabase:
      SELECT count(*) FROM alert_log
      WHERE ticker = '{ticker}'
        AND verdict = '{verdict}'
        AND sent_at >= '{batas_waktu}'

    JIKA count > 0: KEMBALIKAN True   ← masih dalam cooldown
    KEMBALIKAN False                   ← aman untuk dikirim

  KECUALI error:
    LOG ERROR "tidak bisa cek cooldown: {error}"
    KEMBALIKAN None   ← PENTING: None berarti "tidak pasti" → run.py akan skip
```

### Fungsi: `count_alerts_today()`

```
FUNGSI count_alerts_today():
  awal_hari = hari_ini_UTC jam 00:00:00

  COBA:
    query ke Supabase:
      SELECT count(*) FROM alert_log
      WHERE sent_at >= '{awal_hari}'

    KEMBALIKAN jumlah

  KECUALI error:
    LOG ERROR "tidak bisa hitung alert hari ini: {error}"
    KEMBALIKAN None   ← run.py akan abort seluruh siklus jika None
```

### Fungsi: `record_alert(ticker, verdict, rating, price)`

```
FUNGSI record_alert(ticker, verdict, rating, price):
  COBA:
    INSERT ke Supabase:
      alert_log (ticker, verdict, rating, price, sent_at)
      VALUES ('{ticker}', '{verdict}', {rating}, {price}, NOW())

    KEMBALIKAN True

  KECUALI error:
    LOG ERROR "gagal catat alert: {error}"
    KEMBALIKAN False
    # Konsekuensi: cooldown tidak akan bekerja untuk alert ini
    # Risiko: alert yang sama bisa dikirim lagi di scan berikutnya
    # Ini diterima — lebih baik alert duplikat daripada crash sistem
```

### Fungsi: `get_pending_count(ticker, verdict)`

```
FUNGSI get_pending_count(ticker, verdict):
  COBA:
    query ke Supabase:
      SELECT count(*) FROM pending_alerts
      WHERE ticker = '{ticker}' AND verdict = '{verdict}'

    KEMBALIKAN count

  KECUALI error:
    LOG ERROR "gagal ambil pending count"
    KEMBALIKAN 0   ← safe default: anggap belum ada pending → akan daftar ulang
```

### Fungsi: `register_pending(ticker, verdict, rating)`

```
FUNGSI register_pending(ticker, verdict, rating):
  COBA:
    INSERT ke Supabase:
      pending_alerts (ticker, verdict, rating, created_at)
      VALUES ('{ticker}', '{verdict}', {rating}, NOW())

    KEMBALIKAN True

  KECUALI error:
    LOG ERROR "gagal daftarkan pending alert"
    KEMBALIKAN False
```

### Fungsi: `purge_expired_pending(max_age_minutes)`

```
FUNGSI purge_expired_pending(max_age_minutes=30):
  batas_waktu = sekarang_UTC - max_age_minutes menit

  COBA:
    DELETE dari Supabase:
      DELETE FROM pending_alerts
      WHERE created_at < '{batas_waktu}'

    LOG INFO "pending lama dihapus"

  KECUALI error:
    LOG WARNING "gagal purge pending — lanjut"
    # Tidak fatal: pending lama akan terus expire secara logis
    # Worst case: satu ticker mendapat +1 pending count yang tidak relevan
```

### Fungsi: `get_all_alerts_today()`

```
FUNGSI get_all_alerts_today():
  awal_hari = hari_ini_UTC jam 00:00:00

  COBA:
    query ke Supabase:
      SELECT ticker, verdict, rating, price, sent_at
      FROM alert_log
      WHERE sent_at >= '{awal_hari}'
      ORDER BY sent_at ASC

    KEMBALIKAN list_of_rows

  KECUALI error:
    LOG ERROR "gagal ambil alert hari ini"
    KEMBALIKAN []   ← session summary akan tetap terkirim, tapi kosong
```

---

## Kenapa `None` bukan `False`?

Ini adalah keputusan desain yang sangat penting:

| Return Value | Artinya |
|---|---|
| `True` | Konfirmasi positif dari database |
| `False` | Konfirmasi negatif dari database |
| `None` | **Database tidak bisa dihubungi** — kondisi tidak diketahui |

`None` secara eksplisit membedakan antara "tidak ada sinyal" (False) dengan "saya tidak bisa menjawab" (None). `run.py` memperlakukan `None` secara defensif — sebagai alasan untuk berhenti.

Kalau `None` diperlakukan seperti `False`, sistem bisa mengirim sinyal duplikat saat Supabase down, karena cooldown tidak terverifikasi.

---

## Diagram Alur Konfirmasi 2-Scan

```
Scan 1: sinyal ABC muncul
   │
   ▼
get_pending_count("ABC", "LONG") → 0
   │
   ▼ (belum cukup konfirmasi)
register_pending("ABC", "LONG", 84.0)
   │
   ▼
SKIP (tidak dispatch scan ini)

──── 10 menit kemudian ────

Scan 2: sinyal ABC masih muncul
   │
   ▼
get_pending_count("ABC", "LONG") → 1
   │
   ▼ (1 pending + scan sekarang = 2 konfirmasi ✓)
DISPATCH alert ABC
record_alert("ABC", "LONG", ...)
```
