-- STAR-ASN scheduler defaults refresh
-- Adds workday preferences and default fallback coordinates for Telegram-driven automation.

ALTER TABLE public.users
    ADD COLUMN IF NOT EXISTS workdays VARCHAR(20);

UPDATE public.users
SET cron_in = NULL
WHERE cron_in IS NOT NULL
  AND lower(btrim(cron_in)) IN ('none', 'null', 'default', '-');

UPDATE public.users
SET cron_out = NULL
WHERE cron_out IS NOT NULL
  AND lower(btrim(cron_out)) IN ('none', 'null', 'default', '-');

UPDATE public.settings
SET value = '07:00'
WHERE key = 'cron_in'
  AND COALESCE(value, '') IN ('', '07:35');

UPDATE public.settings
SET value = '18:00'
WHERE key = 'cron_out'
  AND COALESCE(value, '') IN ('', '17:05');

INSERT INTO public.settings (key, value, description) VALUES
    ('default_latitude', '-7.3995103268718365', 'Default fallback latitude for attendance automation'),
    ('default_longitude', '109.8895225210264', 'Default fallback longitude for attendance automation'),
    ('default_workdays', 'mon-fri', 'Default active workdays for personal automation'),
    ('cron_in', '07:00', 'Default personal scheduler check-in time'),
    ('cron_out', '18:00', 'Default personal scheduler check-out time')
ON CONFLICT (key) DO UPDATE
SET value = EXCLUDED.value,
    description = EXCLUDED.description;
