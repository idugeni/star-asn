-- RLS policies for internal tables to satisfy Supabase linter
-- These tables are used for internal job queueing and migration tracking.
-- They should not be accessible via the external Supabase API (PostgREST/Realtime).

-- 1. pgqueuer_log
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'pgqueuer_log') THEN
        ALTER TABLE public.pgqueuer_log ENABLE ROW LEVEL SECURITY;
        REVOKE ALL ON TABLE public.pgqueuer_log FROM anon, authenticated;
        DROP POLICY IF EXISTS "Service role can manage pgqueuer_log" ON public.pgqueuer_log;
        CREATE POLICY "Service role can manage pgqueuer_log"
            ON public.pgqueuer_log
            FOR ALL TO service_role
            USING (true)
            WITH CHECK (true);
    END IF;
END $$;

-- 2. pgqueuer_schedules
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'pgqueuer_schedules') THEN
        ALTER TABLE public.pgqueuer_schedules ENABLE ROW LEVEL SECURITY;
        REVOKE ALL ON TABLE public.pgqueuer_schedules FROM anon, authenticated;
        DROP POLICY IF EXISTS "Service role can manage pgqueuer_schedules" ON public.pgqueuer_schedules;
        CREATE POLICY "Service role can manage pgqueuer_schedules"
            ON public.pgqueuer_schedules
            FOR ALL TO service_role
            USING (true)
            WITH CHECK (true);
    END IF;
END $$;

-- 3. pgqueuer_statistics
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'pgqueuer_statistics') THEN
        ALTER TABLE public.pgqueuer_statistics ENABLE ROW LEVEL SECURITY;
        REVOKE ALL ON TABLE public.pgqueuer_statistics FROM anon, authenticated;
        DROP POLICY IF EXISTS "Service role can manage pgqueuer_statistics" ON public.pgqueuer_statistics;
        CREATE POLICY "Service role can manage pgqueuer_statistics"
            ON public.pgqueuer_statistics
            FOR ALL TO service_role
            USING (true)
            WITH CHECK (true);
    END IF;
END $$;

-- 4. schema_migrations
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'schema_migrations') THEN
        ALTER TABLE public.schema_migrations ENABLE ROW LEVEL SECURITY;
        REVOKE ALL ON TABLE public.schema_migrations FROM anon, authenticated;
        DROP POLICY IF EXISTS "Service role can manage schema_migrations" ON public.schema_migrations;
        CREATE POLICY "Service role can manage schema_migrations"
            ON public.schema_migrations
            FOR ALL TO service_role
            USING (true)
            WITH CHECK (true);
    END IF;
END $$;
