-- STAR-ASN Enum Optimization (v2)
-- Converts VARCHAR columns with fixed sets of values to PostgreSQL ENUM types
-- for better data integrity and performance.

-- 1. Define New Enum Types
DO $$ BEGIN
    CREATE TYPE audit_status AS ENUM ('success', 'failed', 'error', 'pending', 'skipped');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE audit_action AS ENUM ('login', 'logout', 'checkin', 'checkout', 'registration', 'update_profile', 'in', 'out', 'other');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE workday_preset AS ENUM ('mon-fri', 'mon-sat', 'everyday');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- 2. Drop policies that depend on users.role to allow type alteration
DROP POLICY IF EXISTS "Personnel access policy (view)" ON public.users;
DROP POLICY IF EXISTS "Personnel access policy (update)" ON public.users;
DROP POLICY IF EXISTS "Personnel access policy (insert)" ON public.users;
DROP POLICY IF EXISTS "Personnel access policy (delete)" ON public.users;
DROP POLICY IF EXISTS "Users can view own logs" ON public.audit_logs;
DROP POLICY IF EXISTS "Admins can manage UPTs (insert)" ON public.upts;
DROP POLICY IF EXISTS "Admins can manage UPTs (update)" ON public.upts;
DROP POLICY IF EXISTS "Admins can manage UPTs (delete)" ON public.upts;
DROP POLICY IF EXISTS "Admins can manage settings (insert)" ON public.settings;
DROP POLICY IF EXISTS "Admins can manage settings (update)" ON public.settings;
DROP POLICY IF EXISTS "Admins can manage settings (delete)" ON public.settings;

-- 3. Alter columns to use Enum types

-- users.role
DO $$
BEGIN
    IF (SELECT data_type FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'role') = 'character varying' THEN
        ALTER TABLE public.users ALTER COLUMN role TYPE user_role USING role::user_role;
    END IF;
END $$;

-- users.workdays
DO $$
BEGIN
    IF (SELECT data_type FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'workdays') = 'character varying' THEN
        ALTER TABLE public.users 
            ALTER COLUMN workdays TYPE workday_preset 
            USING (
                CASE 
                    WHEN workdays = 'mon-fri' THEN 'mon-fri'::workday_preset
                    WHEN workdays = 'mon-sat' THEN 'mon-sat'::workday_preset
                    WHEN workdays = 'everyday' THEN 'everyday'::workday_preset
                    ELSE 'mon-fri'::workday_preset
                END
            );
    END IF;
END $$;

-- audit_logs.status
DO $$
BEGIN
    IF (SELECT data_type FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'audit_logs' AND column_name = 'status') = 'character varying' THEN
        ALTER TABLE public.audit_logs 
            ALTER COLUMN status TYPE audit_status 
            USING (
                CASE 
                    WHEN status = 'success' THEN 'success'::audit_status
                    WHEN status = 'failed' THEN 'failed'::audit_status
                    WHEN status = 'error' THEN 'error'::audit_status
                    WHEN status = 'pending' THEN 'pending'::audit_status
                    WHEN status = 'skipped' THEN 'skipped'::audit_status
                    ELSE 'error'::audit_status
                END
            );
    END IF;
END $$;

-- audit_logs.action
DO $$
BEGIN
    IF (SELECT data_type FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'audit_logs' AND column_name = 'action') = 'character varying' THEN
        ALTER TABLE public.audit_logs 
            ALTER COLUMN action TYPE audit_action 
            USING (
                CASE 
                    WHEN action = 'login' THEN 'login'::audit_action
                    WHEN action = 'logout' THEN 'logout'::audit_action
                    WHEN action = 'checkin' THEN 'checkin'::audit_action
                    WHEN action = 'checkout' THEN 'checkout'::audit_action
                    WHEN action = 'registration' THEN 'registration'::audit_action
                    WHEN action = 'update_profile' THEN 'update_profile'::audit_action
                    WHEN action = 'in' THEN 'in'::audit_action
                    WHEN action = 'out' THEN 'out'::audit_action
                    ELSE 'other'::audit_action
                END
            );
    END IF;
END $$;

-- attendance_job_locks
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'attendance_job_locks') THEN
        IF (SELECT data_type FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'attendance_job_locks' AND column_name = 'action') = 'character varying' THEN
            ALTER TABLE public.attendance_job_locks 
                ALTER COLUMN action TYPE audit_action 
                USING (
                    CASE 
                        WHEN action = 'checkin' THEN 'checkin'::audit_action
                        WHEN action = 'checkout' THEN 'checkout'::audit_action
                        WHEN action = 'in' THEN 'in'::audit_action
                        WHEN action = 'out' THEN 'out'::audit_action
                        ELSE 'other'::audit_action
                    END
                );
        END IF;
    END IF;
END $$;

-- attendance_dead_letters
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'attendance_dead_letters') THEN
        IF (SELECT data_type FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'attendance_dead_letters' AND column_name = 'action') = 'character varying' THEN
            ALTER TABLE public.attendance_dead_letters 
                ALTER COLUMN action TYPE audit_action 
                USING (
                    CASE 
                        WHEN action = 'checkin' THEN 'checkin'::audit_action
                        WHEN action = 'checkout' THEN 'checkout'::audit_action
                        WHEN action = 'in' THEN 'in'::audit_action
                        WHEN action = 'out' THEN 'out'::audit_action
                        ELSE 'other'::audit_action
                    END
                );
        END IF;
    END IF;
END $$;

-- 4. Re-create the policies
-- USERS
CREATE POLICY "Personnel access policy (view)" ON public.users 
    FOR SELECT TO authenticated 
    USING ((SELECT auth.uid()) = id OR (SELECT role FROM public.users WHERE id = (SELECT auth.uid())) = 'admin');

CREATE POLICY "Personnel access policy (update)" ON public.users 
    FOR UPDATE TO authenticated 
    USING ((SELECT auth.uid()) = id OR (SELECT role FROM public.users WHERE id = (SELECT auth.uid())) = 'admin')
    WITH CHECK ((SELECT auth.uid()) = id OR (SELECT role FROM public.users WHERE id = (SELECT auth.uid())) = 'admin');

CREATE POLICY "Personnel access policy (insert)" ON public.users
    FOR INSERT TO authenticated
    WITH CHECK ((SELECT role FROM public.users WHERE id = (SELECT auth.uid())) = 'admin');

CREATE POLICY "Personnel access policy (delete)" ON public.users
    FOR DELETE TO authenticated
    USING ((SELECT role FROM public.users WHERE id = (SELECT auth.uid())) = 'admin');

-- AUDIT_LOGS
CREATE POLICY "Users can view own logs" ON public.audit_logs 
    FOR SELECT TO authenticated 
    USING ((SELECT auth.uid()) = user_id OR nip = (SELECT nip FROM public.users WHERE id = (SELECT auth.uid())) OR (SELECT role FROM public.users WHERE id = (SELECT auth.uid())) = 'admin');

-- UPTS
CREATE POLICY "Admins can manage UPTs (insert)" ON public.upts
    FOR INSERT TO authenticated
    WITH CHECK ((SELECT role FROM public.users WHERE id = (SELECT auth.uid())) = 'admin');

CREATE POLICY "Admins can manage UPTs (update)" ON public.upts
    FOR UPDATE TO authenticated
    USING ((SELECT role FROM public.users WHERE id = (SELECT auth.uid())) = 'admin');

CREATE POLICY "Admins can manage UPTs (delete)" ON public.upts
    FOR DELETE TO authenticated
    USING ((SELECT role FROM public.users WHERE id = (SELECT auth.uid())) = 'admin');

-- SETTINGS
CREATE POLICY "Admins can manage settings (insert)" ON public.settings
    FOR INSERT TO authenticated
    WITH CHECK ((SELECT role FROM public.users WHERE id = (SELECT auth.uid())) = 'admin');

CREATE POLICY "Admins can manage settings (update)" ON public.settings
    FOR UPDATE TO authenticated
    USING ((SELECT role FROM public.users WHERE id = (SELECT auth.uid())) = 'admin');

CREATE POLICY "Admins can manage settings (delete)" ON public.settings
    FOR DELETE TO authenticated
    USING ((SELECT role FROM public.users WHERE id = (SELECT auth.uid())) = 'admin');
