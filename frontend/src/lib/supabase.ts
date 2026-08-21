/**
 * Supabase browser client.  ⚠ SHARED
 *
 * Anon key only — it is public by design. Every write goes through FastAPI,
 * which holds the service key. Do not reach for the service key here, and do
 * not query tables directly from the browser: candidate PII and interview
 * recordings are behind the API on purpose.
 */

import { createClient } from "@supabase/supabase-js";

export const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY,
);
