-- ============================================================
-- NEXUS — Database Schema Setup (Supabase)
-- Jalankan sekali via Supabase SQL Editor
-- ============================================================

-- Tabel 1: Log alert yang sudah terkirim (untuk cek cooldown & ringkasan harian)
create table if not exists alert_log (
    id         bigserial primary key,
    ticker     text        not null,
    verdict    text        not null,       -- STRONG_LONG / LONG / SHORT / STRONG_SHORT
    rating     numeric(5,1) not null,
    price      numeric(12,2) not null,
    sent_at    timestamptz  not null default now()
);

create index if not exists idx_alert_log_ticker_verdict
    on alert_log (ticker, verdict, sent_at desc);

create index if not exists idx_alert_log_sent_at
    on alert_log (sent_at desc);

-- Tabel 2: Pending alerts (menunggu konfirmasi scan berikutnya)
create table if not exists pending_alerts (
    id          bigserial primary key,
    ticker      text         not null,
    verdict     text         not null,
    rating      numeric(5,1) not null,
    created_at  timestamptz  not null default now()
);

create index if not exists idx_pending_alerts_lookup
    on pending_alerts (ticker, verdict, created_at desc);

-- Row Level Security (aktifkan setelah menguji akses)
alter table alert_log    enable row level security;
alter table pending_alerts enable row level security;

-- Policy: hanya service role yang bisa baca & tulis
-- (GitHub Actions menggunakan SUPABASE_KEY sebagai service role key)
create policy "service_full_access_alert_log"
    on alert_log for all
    using (true);

create policy "service_full_access_pending_alerts"
    on pending_alerts for all
    using (true);

-- Scheduled cleanup (opsional): hapus log lebih dari 90 hari
-- Jalankan via Supabase pg_cron extension bila tersedia:
-- select cron.schedule('nexus-cleanup', '0 1 * * *',
--   $$delete from alert_log where sent_at < now() - interval '90 days'$$);
