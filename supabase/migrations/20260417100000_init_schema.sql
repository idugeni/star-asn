-- STAR-ASN Enterprise Hardening Schema
-- Purpose: Enable UUID-based PKs and Row Level Security (RLS)

-- 1. Enable Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 2. Define User Roles Enum
DO $$ BEGIN
    CREATE TYPE user_role AS ENUM ('admin', 'user', 'system');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- 2.1 Cleanup Residue (Legacy Indexes & Policies)
DROP INDEX IF EXISTS ix_audit_logs_nip;
DROP POLICY IF EXISTS "Admins have full access to users" ON users;
DROP POLICY IF EXISTS "Users can view and update own profile" ON users;
DROP POLICY IF EXISTS "Users can update own non-sensitive fields" ON users;
DROP POLICY IF EXISTS "System can insert logs" ON audit_logs;
DROP POLICY IF EXISTS "Restrict audit modification" ON audit_logs;
DROP POLICY IF EXISTS "Authenticated users can view UPTs" ON upts;
DROP POLICY IF EXISTS "Admins can manage UPTs (update/delete)" ON upts;
DROP POLICY IF EXISTS "Authenticated users can view settings" ON settings;
DROP POLICY IF EXISTS "Admins can manage settings" ON settings;

-- 3. Enabling RLS on existing tables (assumes SQLAlchemy created them)
-- If tables don't exist yet, this will fail. We'll ensure they are created first via Python 
-- or define them here for a "maximal" push.

-- (Redefining for technical completeness and RLS setup)
CREATE TABLE IF NOT EXISTS upts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nama_upt VARCHAR(255) NOT NULL UNIQUE,
    latitude FLOAT,
    longitude FLOAT,
    address TEXT,
    timezone VARCHAR(50) DEFAULT 'Asia/Jakarta'
);

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    nip VARCHAR(50) NOT NULL UNIQUE,
    nama VARCHAR(255) NOT NULL,
    encrypted_password TEXT,
    upt_id UUID REFERENCES upts(id),
    telegram_id JSONB UNIQUE,
    cron_in VARCHAR(10) DEFAULT '07:35',
    cron_out VARCHAR(10) DEFAULT '17:05',
    role user_role DEFAULT 'user',
    is_admin BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    personal_latitude FLOAT,
    personal_longitude FLOAT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

CREATE TABLE IF NOT EXISTS user_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    nip VARCHAR(50),
    data JSONB NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    nip VARCHAR(50) NOT NULL,
    action VARCHAR(50) NOT NULL,
    status VARCHAR(20) NOT NULL,
    message TEXT,
    response_time FLOAT,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now())
);

CREATE TABLE IF NOT EXISTS settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT,
    description VARCHAR(255)
);

-- 4. Enable Row Level Security
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE upts ENABLE ROW LEVEL SECURITY;
ALTER TABLE settings ENABLE ROW LEVEL SECURITY;

-- USERS Table
-- Optimized: Consolidated Admin and User-Self access into single policies
-- Performance: Using (SELECT auth.uid()) for caching and TO authenticated for isolation
DROP POLICY IF EXISTS "Personnel access policy (view)" ON users;
CREATE POLICY "Personnel access policy (view)" ON users 
    FOR SELECT TO authenticated 
    USING (
        (SELECT auth.uid()) = id 
        OR 
        (SELECT role FROM users WHERE id = (SELECT auth.uid())) = 'admin'
    );

DROP POLICY IF EXISTS "Personnel access policy (update)" ON users;
CREATE POLICY "Personnel access policy (update)" ON users 
    FOR UPDATE TO authenticated 
    USING (
        (SELECT auth.uid()) = id 
        OR 
        (SELECT role FROM users WHERE id = (SELECT auth.uid())) = 'admin'
    )
    WITH CHECK (
        (SELECT auth.uid()) = id 
        OR 
        (SELECT role FROM users WHERE id = (SELECT auth.uid())) = 'admin'
    );

DROP POLICY IF EXISTS "Personnel access policy (insert)" ON users;
CREATE POLICY "Personnel access policy (insert)" ON users
    FOR INSERT TO authenticated
    WITH CHECK ((SELECT role FROM users WHERE id = (SELECT auth.uid())) = 'admin');

DROP POLICY IF EXISTS "Personnel access policy (delete)" ON users;
CREATE POLICY "Personnel access policy (delete)" ON users
    FOR DELETE TO authenticated
    USING ((SELECT role FROM users WHERE id = (SELECT auth.uid())) = 'admin');

-- AUDIT_LOGS Table
-- Optimized: Performance caching for auth references
DROP POLICY IF EXISTS "Users can view own logs" ON audit_logs;
CREATE POLICY "Users can view own logs" ON audit_logs 
    FOR SELECT TO authenticated 
    USING (
        (SELECT auth.uid()) = user_id 
        OR 
        nip = (SELECT nip FROM users WHERE id = (SELECT auth.uid()))
        OR
        (SELECT role FROM users WHERE id = (SELECT auth.uid())) = 'admin'
    );

-- Backend System can manage logs (restricted to service_role for peak security)
DROP POLICY IF EXISTS "System can manage logs" ON audit_logs;
CREATE POLICY "System can manage logs" ON audit_logs 
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- Explicitly deny modification/deletion for all others to preserve audit integrity
DROP POLICY IF EXISTS "Restrict audit update" ON audit_logs;
CREATE POLICY "Restrict audit update" ON audit_logs
    FOR UPDATE TO authenticated
    USING (false)
    WITH CHECK (false);

DROP POLICY IF EXISTS "Restrict audit deletion" ON audit_logs;
CREATE POLICY "Restrict audit deletion" ON audit_logs
    FOR DELETE TO authenticated
    USING (false);

-- USER_SESSIONS Table
-- Performance: Users can only see/manage their own cookies
DROP POLICY IF EXISTS "Users can manage own sessions" ON user_sessions;
CREATE POLICY "Users can manage own sessions" ON user_sessions
    FOR ALL TO authenticated
    USING ((SELECT auth.uid()) = user_id)
    WITH CHECK ((SELECT auth.uid()) = user_id);

-- UPTS Table
DROP POLICY IF EXISTS "Authenticated users can view UPTs" ON upts;
CREATE POLICY "Authenticated users can view UPTs" ON upts 
    FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "Admins can manage UPTs (insert)" ON upts;
CREATE POLICY "Admins can manage UPTs (insert)" ON upts
    FOR INSERT TO authenticated
    WITH CHECK ((SELECT role FROM users WHERE id = (SELECT auth.uid())) = 'admin');

DROP POLICY IF EXISTS "Admins can manage UPTs (update)" ON upts;
CREATE POLICY "Admins can manage UPTs (update)" ON upts
    FOR UPDATE TO authenticated
    USING ((SELECT role FROM users WHERE id = (SELECT auth.uid())) = 'admin');

DROP POLICY IF EXISTS "Admins can manage UPTs (delete)" ON upts;
CREATE POLICY "Admins can manage UPTs (delete)" ON upts
    FOR DELETE TO authenticated
    USING ((SELECT role FROM users WHERE id = (SELECT auth.uid())) = 'admin');

-- SETTINGS Table
-- Performance: Separate SELECT and Write policies to avoid "Multiple Permissive Policies"
DROP POLICY IF EXISTS "Authenticated users can view settings" ON settings;
CREATE POLICY "Authenticated users can view settings" ON settings 
    FOR SELECT TO authenticated USING (true);

DROP POLICY IF EXISTS "Admins can manage settings (insert)" ON settings;
CREATE POLICY "Admins can manage settings (insert)" ON settings
    FOR INSERT TO authenticated
    WITH CHECK ((SELECT role FROM users WHERE id = (SELECT auth.uid())) = 'admin');

DROP POLICY IF EXISTS "Admins can manage settings (update)" ON settings;
CREATE POLICY "Admins can manage settings (update)" ON settings
    FOR UPDATE TO authenticated
    USING ((SELECT role FROM users WHERE id = (SELECT auth.uid())) = 'admin');

DROP POLICY IF EXISTS "Admins can manage settings (delete)" ON settings;
CREATE POLICY "Admins can manage settings (delete)" ON settings
    FOR DELETE TO authenticated
    USING ((SELECT role FROM users WHERE id = (SELECT auth.uid())) = 'admin');

-- 6. Indices for Performance
CREATE INDEX IF NOT EXISTS idx_users_nip ON users(nip);
CREATE INDEX IF NOT EXISTS idx_users_upt_id ON users(upt_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_nip ON audit_logs(nip);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON audit_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_user_sessions_user_id ON user_sessions(user_id);
