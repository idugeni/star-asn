-- STAR-ASN Action Recovery
-- Recovers 'in' and 'out' actions that were incorrectly mapped to 'other' during enum optimization.

-- 1. Recover audit_logs actions based on message content
UPDATE public.audit_logs
SET action = 'in'::audit_action
WHERE action = 'other'::audit_action
  AND (message ILIKE 'Sudah absen in:%' OR message ILIKE 'Berhasil submit absen' OR message ILIKE 'Berhasil submit (HTML detected)');

UPDATE public.audit_logs
SET action = 'out'::audit_action
WHERE action = 'other'::audit_action
  AND message ILIKE 'Sudah absen out:%';

-- 2. Recover dead letters if possible (less critical but good for audit)
UPDATE public.attendance_dead_letters
SET action = 'in'::audit_action
WHERE action = 'other'::audit_action
  AND payload->>'action' = 'in';

UPDATE public.attendance_dead_letters
SET action = 'out'::audit_action
WHERE action = 'other'::audit_action
  AND payload->>'action' = 'out';

-- 3. Recover job locks
UPDATE public.attendance_job_locks
SET action = 'in'::audit_action
WHERE action = 'other'::audit_action
  AND lock_key ILIKE 'in_%';

UPDATE public.attendance_job_locks
SET action = 'out'::audit_action
WHERE action = 'other'::audit_action
  AND lock_key ILIKE 'out_%';
