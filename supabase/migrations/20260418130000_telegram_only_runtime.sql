-- STAR-ASN Telegram-only runtime migration
-- Aligns bootstrap-first schema with runtime models and Telegram-only control plane.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'users'
          AND column_name = 'encrypted_password'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'users'
          AND column_name = 'password'
    ) THEN
        ALTER TABLE public.users RENAME COLUMN encrypted_password TO password;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'users'
          AND column_name = 'telegram_id'
          AND data_type = 'jsonb'
    ) THEN
        ALTER TABLE public.users ADD COLUMN IF NOT EXISTS telegram_id_v2 BIGINT;

        UPDATE public.users
        SET telegram_id_v2 = CASE
            WHEN telegram_id IS NULL THEN NULL
            WHEN jsonb_typeof(telegram_id) = 'number' THEN (telegram_id::text)::BIGINT
            WHEN jsonb_typeof(telegram_id) = 'string' THEN NULLIF(trim(both '"' FROM telegram_id::text), '')::BIGINT
            WHEN jsonb_typeof(telegram_id) = 'object' AND telegram_id ? 'id' THEN NULLIF(telegram_id ->> 'id', '')::BIGINT
            ELSE NULL
        END
        WHERE telegram_id IS NOT NULL;

        IF EXISTS (
            SELECT 1
            FROM (
                SELECT telegram_id_v2
                FROM public.users
                WHERE telegram_id_v2 IS NOT NULL
                GROUP BY telegram_id_v2
                HAVING COUNT(*) > 1
            ) dup
        ) THEN
            RAISE EXCEPTION 'Duplicate telegram_id values detected during BIGINT migration.';
        END IF;

        ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_telegram_id_key;
        DROP INDEX IF EXISTS ix_users_telegram_id;
        ALTER TABLE public.users DROP COLUMN telegram_id;
        ALTER TABLE public.users RENAME COLUMN telegram_id_v2 TO telegram_id;
    END IF;
END $$;

ALTER TABLE public.users ALTER COLUMN telegram_id TYPE BIGINT USING telegram_id::BIGINT;

DROP INDEX IF EXISTS ix_users_telegram_id;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_telegram_id_unique
    ON public.users (telegram_id)
    WHERE telegram_id IS NOT NULL;
