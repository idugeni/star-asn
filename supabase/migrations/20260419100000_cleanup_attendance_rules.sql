-- STAR-ASN Enterprise Architecture Cleanup
-- Purpose: Remove obsolete attendance rules to simplify automation logic.
-- Related: d:\GITHUB\star_asn\star_attendance\database_manager.py

-- 1. Remove obsolete settings keys
DELETE FROM public.settings 
WHERE key IN ('rule_in_before', 'rule_out_after', 'rule_mode', 'rule_work_hours');

-- 2. Verify settings table integrity (optional, but good for enterprise)
ANALYZE public.settings;
