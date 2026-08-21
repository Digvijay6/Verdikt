/// <reference types="vite/client" />

/**
 * Only VITE_-prefixed variables reach the browser. Nothing secret belongs
 * here — the Supabase anon key is public by design, and the service key must
 * never appear in this file or anywhere else the client can read.
 */
interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_SUPABASE_URL: string;
  readonly VITE_SUPABASE_ANON_KEY: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
