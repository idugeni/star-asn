-- STAR-ASN UPT Schema Cleanup
-- Purpose: Remove redundant/unused columns from 'upts' table.
-- Related: d:\GITHUB\star_asn\star_attendance\db\models.py

-- 1. Drop unused columns from upts table
ALTER TABLE public.upts 
    DROP COLUMN IF EXISTS latitude,
    DROP COLUMN IF EXISTS longitude,
    DROP COLUMN IF EXISTS address;

-- 2. Verify table structure
ANALYZE public.upts;
