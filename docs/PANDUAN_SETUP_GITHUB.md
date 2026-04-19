# PANDUAN SETUP NEXUS ENGINE DI GITHUB
## Dari Nol Sampai Sistem Berjalan Otomatis

---

## Gambaran Besar

Setelah selesai, sistem akan:
- Berjalan otomatis setiap 10 menit saat market IDX buka (Senin–Jumat 09:00–15:50 WIB)
- Menganalisa 45 saham LQ45
- Mengirim notifikasi ke Telegram group kamu
- Semua gratis, tanpa VPS, tanpa server pribadi

```
Kamu upload code ke GitHub
        ↓
GitHub Actions menjalankan kode secara otomatis (gratis)
        ↓
Kode mengambil data saham dari Yahoo Finance
        ↓
Kode menganalisa dan menyimpan state ke Supabase (gratis)
        ↓
Notifikasi dikirim ke Telegram group kamu (gratis)
```

**Estimasi waktu setup: 30–45 menit**

---

## BAGIAN 1 — SIAPKAN TELEGRAM BOT

### Langkah 1.1 — Buat Bot Baru

1. Buka Telegram di HP atau PC
2. Cari `@BotFather` di kotak pencarian → pilih yang ada centang biru
3. Ketik `/newbot` dan kirim
4. BotFather akan tanya nama bot kamu (tampil di Telegram) → ketik misalnya: `NEXUS Trading Alerts`
5. BotFather akan tanya username bot (harus diakhiri `bot`) → ketik misalnya: `nexus_trading_bot`
6. BotFather akan memberi **TOKEN** seperti ini:
   ```
   1234567890:ABCDefGhIJKlmNoPQRsTUVwxyz
   ```
   **Simpan token ini — akan dipakai nanti sebagai secret GitHub**

### Langkah 1.2 — Buat Group Telegram

1. Buat grup Telegram baru (nama bebas, misalnya "NEXUS Signals")
2. Tambahkan bot yang baru dibuat ke grup tersebut
3. Beri bot akses **admin** di grup (agar bisa kirim pesan)

### Langkah 1.3 — Dapatkan Chat ID Grup

1. Tambahkan `@userinfobot` ke grup yang sama
2. Ketik `/start` di grup
3. Bot akan membalas dengan info grup, catat **Chat ID** (angka negatif, contoh: `-1001234567890`)
4. Keluarkan `@userinfobot` dari grup setelah dapat Chat ID-nya

> **Alternatif:** Kunjungi `https://api.telegram.org/bot<TOKEN_KAMU>/getUpdates` di browser setelah kirim pesan ke grup — Chat ID akan terlihat di JSON response

---

## BAGIAN 2 — SETUP SUPABASE (DATABASE)

### Langkah 2.1 — Buat Akun & Project

1. Buka [supabase.com](https://supabase.com) → klik **Start your project**
2. Sign up dengan GitHub atau email
3. Klik **New Project**
4. Isi:
   - **Name:** nexus-trading (atau nama lain)
   - **Database Password:** buat password kuat dan simpan
   - **Region:** pilih **Southeast Asia (Singapore)** agar latensi rendah
5. Klik **Create new project** → tunggu 1–2 menit

### Langkah 2.2 — Jalankan Script Database

1. Di Supabase dashboard, klik **SQL Editor** di menu kiri
2. Klik **New query**
3. Buka file `supabase_setup.sql` dari ZIP yang sudah kamu extract
4. Copy **seluruh isi** file tersebut
5. Paste ke SQL Editor Supabase
6. Klik **Run** (tombol hijau)
7. Pastikan muncul pesan sukses di bawah (tidak ada error merah)

### Langkah 2.3 — Ambil Credentials Supabase

1. Di Supabase dashboard, klik ikon **Settings** (roda gigi) di menu kiri bawah
2. Pilih **API**
3. Catat dua hal:
   - **Project URL** → contoh: `https://abcdefghij.supabase.co`
   - **Service Role Key** (bukan anon key!) → klik "Reveal" untuk tampilkan

> ⚠️ **PENTING:** Gunakan **service_role** key, BUKAN anon/public key. Service role key ada di bagian bawah halaman API settings. Anon key tidak punya izin write yang cukup.

---

## BAGIAN 3 — BUAT REPOSITORY GITHUB

### Langkah 3.1 — Buat Repository Baru

1. Buka [github.com](https://github.com) → login atau daftar dulu
2. Klik tombol **+** di pojok kanan atas → **New repository**
3. Isi:
   - **Repository name:** `nexus-engine` (atau nama lain)
   - **Visibility:** pilih **Public** ← WAJIB PUBLIC agar GitHub Actions gratis unlimited
   - **Jangan centang** "Add a README file" (kita akan upload file sendiri)
4. Klik **Create repository**
5. GitHub akan tampilkan halaman kosong dengan instruksi upload

### Langkah 3.2 — Upload File dari ZIP

**Cara termudah: Upload via GitHub Web (tanpa Git)**

1. Di halaman repository yang baru dibuat, klik link **"uploading an existing file"**

2. Extract file ZIP `NEXUS-Engine.zip` di komputer kamu terlebih dahulu

3. Di dalam folder hasil extract (`nexus-engine/`), kamu akan melihat:
   ```
   nexus-engine/
   ├── run.py
   ├── dry_run.py
   ├── requirements.txt
   ├── supabase_setup.sql
   ├── core/
   ├── config/
   ├── .github/
   └── docs/
   ```

4. Di halaman upload GitHub, **drag & drop seluruh isi folder** `nexus-engine/` ke area upload

   > ⚠️ Drag isi folder, bukan folder-nya sendiri. Yang terupload harus `run.py`, bukan `nexus-engine/run.py`.

5. Tunggu semua file selesai upload (progress bar akan terlihat)

6. Di bagian bawah, isi commit message: `Initial commit — NEXUS Engine v1.0`

7. Klik **Commit changes**

### Langkah 3.3 — Verifikasi Struktur di GitHub

Setelah commit, pastikan struktur terlihat seperti ini di GitHub:

```
repository/
├── run.py                    ← ada di root
├── dry_run.py                ← ada di root
├── requirements.txt          ← ada di root
├── supabase_setup.sql        ← ada di root
├── core/
│   ├── __init__.py
│   ├── engine.py
│   ├── fetcher.py
│   ├── dispatcher.py
│   └── ledger.py
├── config/
│   ├── __init__.py
│   ├── params.py
│   └── universe.py
├── .github/
│   └── workflows/
│       └── pulse.yml         ← FILE PALING PENTING
└── docs/
    └── ...
```

> Kalau `.github/workflows/pulse.yml` tidak terlihat (karena folder `.github` diawali titik), pastikan file itu ada: buka folder `.github` → `workflows` → pastikan `pulse.yml` ada di sana.

---

## BAGIAN 4 — KONFIGURASI GITHUB SECRETS

Secrets adalah tempat menyimpan password/token agar tidak terekspos di kode.

### Langkah 4.1 — Buka Halaman Secrets

1. Di halaman repository GitHub kamu, klik tab **Settings**
2. Di menu kiri, klik **Secrets and variables** → **Actions**
3. Klik **New repository secret**

### Langkah 4.2 — Tambahkan 4 Secret Wajib

Tambahkan satu per satu dengan klik "New repository secret" setiap kali:

---

**Secret 1:**
- Name: `TELEGRAM_BOT_TOKEN`
- Secret: token dari BotFather (contoh: `1234567890:ABCDefGhIJKlmNoPQRsTUVwxyz`)
- Klik **Add secret**

---

**Secret 2:**
- Name: `TELEGRAM_CHAT_ID`
- Secret: Chat ID grup Telegram (contoh: `-1001234567890`)
- Klik **Add secret**

---

**Secret 3:**
- Name: `SUPABASE_URL`
- Secret: Project URL Supabase (contoh: `https://abcdefghij.supabase.co`)
- Klik **Add secret**

---

**Secret 4:**
- Name: `SUPABASE_KEY`
- Secret: Service Role Key Supabase (string panjang ~200 karakter)
- Klik **Add secret**

---

**Secret 5 (Opsional — data cadangan):**
- Name: `TWELVEDATA_API_KEY`
- Secret: API key dari [twelvedata.com](https://twelvedata.com) (daftar gratis, 800 kredit/hari)
- Klik **Add secret**

> Kalau tidak punya Twelve Data key, tidak perlu ditambahkan. Sistem tetap berjalan menggunakan Yahoo Finance saja.

### Langkah 4.3 — Verifikasi Secrets

Setelah selesai, halaman Secrets harus menampilkan:
```
SUPABASE_KEY          Updated X minutes ago
SUPABASE_URL          Updated X minutes ago
TELEGRAM_BOT_TOKEN    Updated X minutes ago
TELEGRAM_CHAT_ID      Updated X minutes ago
TWELVEDATA_API_KEY    Updated X minutes ago  (opsional)
```

---

## BAGIAN 5 — AKTIFKAN GITHUB ACTIONS

### Langkah 5.1 — Enable Actions

1. Di repository GitHub, klik tab **Actions**
2. Jika ada pesan "Workflows aren't being run on this forked repository" atau tombol enable → klik **I understand my workflows, go ahead and enable them**

### Langkah 5.2 — Uji Coba Manual (WAJIB sebelum tunggu jadwal)

Jangan tunggu jadwal otomatis dulu. Uji sekarang:

1. Di tab **Actions**, klik workflow **"NEXUS Market Pulse"** di menu kiri
2. Klik tombol **"Run workflow"** → **Run workflow** (konfirmasi)
3. Tunggu 30–60 detik → refresh halaman
4. Kamu akan melihat satu run muncul dengan ikon bulat

**Baca hasilnya:**
- ✅ **Lingkaran hijau** = sukses, cek Telegram kamu
- ❌ **Lingkaran merah** = ada error, klik nama run → baca log

### Langkah 5.3 — Baca Log Jika Ada Error

1. Klik pada run yang merah
2. Klik **"run-nexus"** di panel kiri
3. Expand bagian **"Run NEXUS"**
4. Baca pesan error yang muncul

**Error umum dan solusinya:**

| Pesan Error | Penyebab | Solusi |
|---|---|---|
| `SUPABASE_URL atau SUPABASE_KEY tidak ditemukan` | Secret belum ditambahkan atau salah nama | Cek kembali nama secret di Settings → Secrets |
| `EnvironmentError` | Env variable kosong | Pastikan tidak ada spasi di value secret |
| `HTTPError 401` | Supabase key salah (pakai anon bukan service_role) | Ganti dengan service_role key |
| `Telegram send failed` | Token bot salah atau bot belum di grup | Cek token & pastikan bot sudah di grup |
| `ModuleNotFoundError: yfinance` | requirements.txt tidak terbaca | Pastikan `requirements.txt` ada di root repository |

---

## BAGIAN 6 — VERIFIKASI SISTEM BERJALAN

### Checklist Verifikasi

Setelah manual run sukses (lingkaran hijau):

- [ ] Cek Telegram → apakah ada pesan masuk dari bot?
  - Kalau tidak ada pesan: mungkin tidak ada saham yang memenuhi threshold 65/100 saat itu. Normal.
  - Mendekati jam 15:50 WIB: akan ada pesan ringkasan sesi
- [ ] Cek Supabase: buka SQL Editor → jalankan `SELECT * FROM alert_log LIMIT 10;`
  - Kalau ada data = sistem sudah mencatat alert
- [ ] Cek jadwal: di tab **Actions** → **NEXUS Market Pulse** → pastikan ada tanda "Scheduled" di samping nama workflow

### Tes Dry Run Lokal (Opsional)

Kalau kamu punya Python di komputer:

```bash
# Extract ZIP dan masuk ke folder
cd nexus-engine

# Install dependencies
pip install pandas numpy

# Jalankan simulator offline (tidak butuh internet, tidak kirim ke Telegram)
python dry_run.py
```

Output akan menampilkan simulasi lengkap rating, verdict, dan preview pesan — tanpa menyentuh server manapun.

---

## BAGIAN 7 — JADWAL OTOMATIS

Setelah setup selesai, sistem berjalan otomatis tanpa kamu lakukan apapun:

| Waktu (WIB) | Yang Terjadi |
|---|---|
| 09:00 | Siklus pertama: scan 45 saham LQ45 |
| 09:10 | Siklus kedua: konfirmasi sinyal scan 1 |
| 09:20 | Sinyal yang terkonfirmasi dikirim ke Telegram |
| ... | Terus berulang setiap 10 menit |
| 15:40 | Siklus terakhir |
| 15:50 | Ringkasan sesi dikirim ke Telegram |
| 16:00+ | Tidak ada siklus (di luar jam market) |

> GitHub Actions menggunakan UTC. Jadwal sistem: `*/10 2-8 * * 1-5` (UTC 02:00–08:59 = WIB 09:00–15:59)

---

## BAGIAN 8 — PERAWATAN RUTIN

### Supabase Free Tier — Cegah Database Di-Pause

Supabase free tier akan **mematikan database** setelah 1 minggu tidak ada aktivitas. Selama sistem berjalan aktif setiap hari, ini tidak masalah.

Tapi kalau ada liburan panjang (> 7 hari sistem tidak jalan):
1. Login ke Supabase dashboard
2. Buka project NEXUS
3. Klik **Restore project** jika sudah di-pause

### Cek Logs Kapan Saja

1. Buka tab **Actions** di GitHub
2. Setiap run akan tersimpan (retensi 30 hari)
3. Run yang gagal akan mengirim email notifikasi ke akun GitHub kamu

### Update Daftar Saham

Edit `config/universe.py` langsung di GitHub (klik ikon pensil pada file).
Setelah save (commit), sistem akan langsung pakai daftar baru di siklus berikutnya.

### Update Parameter/Threshold

Edit `config/params.py` langsung di GitHub.
Tidak perlu restart apapun — GitHub Actions otomatis pakai kode terbaru setiap run.

---

## RINGKASAN SECRETS YANG DIBUTUHKAN

| Secret Name | Wajib? | Dari mana? |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ Wajib | @BotFather di Telegram |
| `TELEGRAM_CHAT_ID` | ✅ Wajib | @userinfobot atau getUpdates API |
| `SUPABASE_URL` | ✅ Wajib | Supabase → Settings → API → Project URL |
| `SUPABASE_KEY` | ✅ Wajib | Supabase → Settings → API → service_role key |
| `TWELVEDATA_API_KEY` | ❌ Opsional | twelvedata.com → daftar gratis |

---

## BIAYA OPERASIONAL

| Komponen | Provider | Biaya |
|---|---|---|
| Scheduler (cron runner) | GitHub Actions (public repo) | **Gratis unlimited** |
| Database state | Supabase Free Tier | **Gratis** (500MB) |
| Data harga saham | Yahoo Finance via yfinance | **Gratis** |
| Data cadangan | Twelve Data (opsional) | **Gratis** (800 kredit/hari) |
| Notifikasi | Telegram Bot API | **Gratis** |
| **TOTAL** | | **Rp 0/bulan** |

---

*NEXUS Engine v1.0 — Dokumen ini adalah bagian dari paket NEXUS-Engine.zip*
