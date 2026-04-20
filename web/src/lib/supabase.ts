import { createClient } from '@supabase/supabase-js';

const SUPABASE_URL = import.meta.env.NEXT_PUBLIC_SUPABASE_URL;
const SUPABASE_KEY = import.meta.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;

if (!SUPABASE_URL || !SUPABASE_KEY) {
  console.warn('Supabase credentials missing. Ensure NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY are set in .env');
}

export const supabase = createClient(SUPABASE_URL || '', SUPABASE_KEY || '');
