-- STAR-ASN Real-time Synchronization Trigger
-- Purpose: Notify the internal API instantly when user data or settings change.
-- Channel: 'scheduler_sync_trigger'

-- 1. Create the notification function
CREATE OR REPLACE FUNCTION public.notify_scheduler_sync()
RETURNS TRIGGER 
SET search_path = ''
AS $$
BEGIN
    -- NOTIFY sends a signal on the specified channel
    -- Using fully qualified pg_catalog.pg_notify for security with empty search_path
    PERFORM pg_catalog.pg_notify('scheduler_sync_trigger', TG_TABLE_NAME);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 2. Add trigger to users table
DROP TRIGGER IF EXISTS tr_notify_users_change ON public.users;
CREATE TRIGGER tr_notify_users_change
    AFTER INSERT OR UPDATE OR DELETE ON public.users
    FOR EACH STATEMENT
    EXECUTE FUNCTION public.notify_scheduler_sync();

-- 3. Add trigger to settings table
DROP TRIGGER IF EXISTS tr_notify_settings_change ON public.settings;
CREATE TRIGGER tr_notify_settings_change
    AFTER INSERT OR UPDATE OR DELETE ON public.settings
    FOR EACH STATEMENT
    EXECUTE FUNCTION public.notify_scheduler_sync();
