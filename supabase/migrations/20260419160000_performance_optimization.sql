-- STAR-ASN Database Performance Hardening
-- Purpose: Optimize index strategy for high-concurrency audit and user lookups.

-- 1. Optimize Audit Logs for fast historical lookups
CREATE INDEX IF NOT EXISTS idx_audit_logs_nip_action_timestamp 
    ON public.audit_logs (nip, action, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_audit_logs_status_timestamp 
    ON public.audit_logs (status, timestamp DESC);

-- 2. Optimize User lookup by Telegram ID (frequent bot interaction)
CREATE INDEX IF NOT EXISTS idx_users_telegram_id_active 
    ON public.users (telegram_id) WHERE (is_active = true);

-- 3. Optimize Session cleanup
CREATE INDEX IF NOT EXISTS idx_user_sessions_updated_at 
    ON public.user_sessions (updated_at DESC);

-- 4. Vacuum and Analyze for statistics update
ANALYZE public.audit_logs;
ANALYZE public.users;
ANALYZE public.user_sessions;
