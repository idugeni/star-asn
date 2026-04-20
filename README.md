# STAR-ASN Telegram-Only Runtime

STAR-ASN sekarang beroperasi dengan Telegram sebagai satu-satunya control plane untuk user dan admin. Web dashboard tidak lagi digunakan.

## Komponen Runtime
- `bot`: control plane resmi untuk registrasi, profil, manual attendance, admin telemetry, global settings, dan manajemen user.
- `worker`: pemroses queue PostgreSQL (`pgqueuer`) untuk job attendance massal.
- `api`: layanan internal untuk health check dan kontrol scheduler lintas proses.
- `bootstrap`: runner satu kali untuk migrasi Supabase dan instalasi schema queue sebelum runtime dimulai.

## Menjalankan Lokal
- Siapkan `.env` dari `.env.example`.
- Jalankan bootstrap dan runtime dengan:
  - `dev.bat`
- Atau manual:
  - `python -m star_attendance.bootstrap_db`
  - `python -m api.main`
  - `python -m star_attendance.worker_pg`
  - `python -m star_attendance.telegram_bot`

## Docker Compose
- `docker compose up --build`
- Compose akan menjalankan urutan:
  - `bootstrap -> api -> worker -> bot`
- Image resmi yang dipakai runtime adalah `star-asn:latest`.
- Hindari membuat image eksperimen dengan nama lain seperti `star-asn-plan-check`; compose sekarang memakai satu entrypoint modular untuk semua role container.
- Healthcheck API, retry startup, dan log rotation container sudah ditangani di compose agar runtime lebih tahan terhadap kegagalan sementara.

## Variabel Penting
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ADMIN_ID`
- `TELEGRAM_LOG_GROUP_ID`
- `POSTGRES_URL`
- `MASTER_SECURITY_KEY`
- `INTERNAL_API_URL`
- `INTERNAL_API_TOKEN`

## Catatan Operasional
- API internal dilindungi dengan header `X-Internal-Token`.
- Scheduler hanya diekspos lewat endpoint internal dan kontrol admin Telegram.
- Bootstrap wajib sukses dulu sebelum bot, worker, atau API dipakai.
