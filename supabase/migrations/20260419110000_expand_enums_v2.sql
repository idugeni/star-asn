-- STAR-ASN Enum Expansion
-- Adds missing values to ENUM types discovered during runtime.

-- 1. Add 'ok' to audit_status
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_enum e 
        JOIN pg_type t ON t.oid = e.enumtypid 
        WHERE t.typname = 'audit_status' AND e.enumlabel = 'ok'
    ) THEN
        ALTER TYPE audit_status ADD VALUE 'ok';
    END IF;
END $$;

-- 2. Add missing values to audit_action
DO $$
DECLARE
    val TEXT;
BEGIN
    FOR val IN SELECT unnest(ARRAY['scheduler_sync', 'settings_update', 'delete_personnel', 'search', 'broadcast', 'abort', 'in', 'out'])
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_enum e 
            JOIN pg_type t ON t.oid = e.enumtypid 
            WHERE t.typname = 'audit_action' AND e.enumlabel = val
        ) THEN
            EXECUTE format('ALTER TYPE audit_action ADD VALUE %L', val);
        END IF;
    END LOOP;
END $$;
