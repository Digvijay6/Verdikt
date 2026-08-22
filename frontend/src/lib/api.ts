/**
 * Typed client for the FastAPI backend.  SHARED — all three lanes import this.
 *
 * Types come from `npm run gen:types`, which reads FastAPI's /openapi.json and
 * regenerates src/types/api.ts. Run it after any Pydantic model change — that
 * regeneration is what keeps the cross-lane contracts honest, so nothing here
 * should ever be hand-typed to work around a stale generated file.
 */

import { supabase } from "./supabase";

const BASE_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  { authenticated = true }: { authenticated?: boolean } = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  // Never set Content-Type for FormData — the browser has to supply the
  // multipart boundary itself, and overriding it silently breaks the upload.
  if (!(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  // Recruiter routes carry a Supabase JWT. Candidate routes (the interview
  // itself) are public and authenticated by the invite token in the body.
  if (authenticated) {
    const {
      data: { session },
    } = await supabase.auth.getSession();
    if (session) headers.set("Authorization", `Bearer ${session.access_token}`);
  }

  const res = await fetch(`${BASE_URL}${path}`, { ...init, headers });

  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, detail || res.statusText);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),

  /** Multipart, for the résumé upload on the public application form. */
  postForm: <T>(path: string, body: FormData) =>
    request<T>(path, { method: "POST", body }, { authenticated: false }),

  /** Public — no session required. The invite token is the auth. */
  redeemInvite: <T>(token: string) =>
    request<T>(
      "/interview/redeem",
      { method: "POST", body: JSON.stringify({ token }) },
      { authenticated: false },
    ),
};

export { ApiError };
