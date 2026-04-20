-- STAR-ASN enterprise finalization
-- Converts legacy naive WIB timestamps to timestamptz, seeds defaults,
-- and hardens internal queue/runtime support objects.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'users'
          AND column_name = 'created_at'
          AND data_type = 'timestamp without time zone'
    ) THEN
        ALTER TABLE public.users
            ALTER COLUMN created_at TYPE TIMESTAMPTZ
            USING created_at AT TIME ZONE 'Asia/Jakarta';
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'users'
          AND column_name = 'updated_at'
          AND data_type = 'timestamp without time zone'
    ) THEN
        ALTER TABLE public.users
            ALTER COLUMN updated_at TYPE TIMESTAMPTZ
            USING updated_at AT TIME ZONE 'Asia/Jakarta';
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'user_sessions'
          AND column_name = 'updated_at'
          AND data_type = 'timestamp without time zone'
    ) THEN
        ALTER TABLE public.user_sessions
            ALTER COLUMN updated_at TYPE TIMESTAMPTZ
            USING updated_at AT TIME ZONE 'Asia/Jakarta';
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'audit_logs'
          AND column_name = 'timestamp'
          AND data_type = 'timestamp without time zone'
    ) THEN
        ALTER TABLE public.audit_logs
            ALTER COLUMN timestamp TYPE TIMESTAMPTZ
            USING "timestamp" AT TIME ZONE 'Asia/Jakarta';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.attendance_job_locks (
    lock_key TEXT PRIMARY KEY,
    request_key TEXT NOT NULL UNIQUE,
    nip VARCHAR(50) NOT NULL,
    action VARCHAR(50) NOT NULL,
    source TEXT NOT NULL,
    scope_date DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now()),
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS public.attendance_dead_letters (
    request_key TEXT PRIMARY KEY,
    nip VARCHAR(50) NOT NULL,
    action VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    reason TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    failed_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc'::text, now())
);

CREATE INDEX IF NOT EXISTS idx_attendance_job_locks_scope
    ON public.attendance_job_locks (nip, action, scope_date);
CREATE INDEX IF NOT EXISTS idx_attendance_job_locks_expires_at
    ON public.attendance_job_locks (expires_at);
CREATE INDEX IF NOT EXISTS idx_attendance_dead_letters_failed_at
    ON public.attendance_dead_letters (failed_at DESC);
CREATE INDEX IF NOT EXISTS idx_attendance_dead_letters_nip_action
    ON public.attendance_dead_letters (nip, action);

ALTER TABLE public.attendance_job_locks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.attendance_dead_letters ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Service role can manage job locks" ON public.attendance_job_locks;
CREATE POLICY "Service role can manage job locks"
    ON public.attendance_job_locks
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

DROP POLICY IF EXISTS "Service role can manage dead letters" ON public.attendance_dead_letters;
CREATE POLICY "Service role can manage dead letters"
    ON public.attendance_dead_letters
    FOR ALL TO service_role
    USING (true)
    WITH CHECK (true);

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'pgqueuer'
    ) THEN
        ALTER TABLE public.pgqueuer ENABLE ROW LEVEL SECURITY;
        REVOKE ALL ON TABLE public.pgqueuer FROM anon, authenticated;
        DROP POLICY IF EXISTS "Service role can manage pgqueuer" ON public.pgqueuer;
        CREATE POLICY "Service role can manage pgqueuer"
            ON public.pgqueuer
            FOR ALL TO service_role
            USING (true)
            WITH CHECK (true);
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public'
          AND p.proname = 'fn_pgqueuer_changed'
    ) THEN
        EXECUTE 'ALTER FUNCTION public.fn_pgqueuer_changed() SET search_path = pg_catalog, public';
    END IF;
END $$;

INSERT INTO public.settings (key, value, description) VALUES
    ('default_location', 'Kabupaten Wonosobo, Jawa Tengah', 'Default formatted location label for UI and telemetry'),
    ('timezone', 'Asia/Jakarta', 'Primary application timezone'),
    ('rule_in_before', '07:30', 'Latest allowed check-in time'),
    ('rule_out_after', '17:00', 'Earliest allowed check-out time'),
    ('rule_mode', 'smart', 'Attendance rule mode'),
    ('rule_work_hours', '8', 'Required work hours before checkout'),
    ('ocr_engine', 'ddddocr', 'Default OCR engine'),
    ('automation_enabled', 'true', 'Enable scheduler-managed personal automation'),
    ('cron_in', '07:35', 'Default personal scheduler check-in time'),
    ('cron_out', '17:05', 'Default personal scheduler check-out time'),
    ('time_storage_version', 'timestamptz_v2', 'Timestamp storage migration marker')
ON CONFLICT (key) DO UPDATE
SET value = EXCLUDED.value,
    description = EXCLUDED.description;
