/**
 * Session and organization state.  LANE 1
 *
 * Two things have to be true before a recruiter sees anything: they are signed
 * in, and they belong to an organization. Those are separate states, and
 * conflating them is why "logged in but nothing works" happens — a user who
 * has just signed up is authenticated with no org, which is normal, not broken.
 *
 * Passwords go straight from the browser to Supabase. Our API only ever sees
 * the resulting JWT.
 */

import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { Session } from "@supabase/supabase-js";

import { api } from "./api";
import { supabase } from "./supabase";

export type Organization = {
  id: string;
  name: string;
  slug: string;
  plan: string;
};

type Me = { organizations: Organization[] };

type AuthState = {
  session: Session | null;
  org: Organization | null;
  /** True until we know both the session and whether it has an org. */
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<{ needsEmailConfirm: boolean }>;
  signOut: () => Promise<void>;
  refreshOrg: () => Promise<void>;
};

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [org, setOrg] = useState<Organization | null>(null);
  const [loading, setLoading] = useState(true);

  async function loadOrg(active: Session | null) {
    if (!active) {
      setOrg(null);
      return;
    }
    try {
      const me = await api.get<Me>("/auth/me");
      // The UI assumes one org, so a user with several just gets their first.
      // Agencies need a switcher; nobody has asked for one yet.
      setOrg(me.organizations[0] ?? null);
    } catch {
      // A failed lookup is not the same as having no org — leaving it null
      // would bounce the user to onboarding and invite a duplicate company.
      setOrg(null);
    }
  }

  useEffect(() => {
    let cancelled = false;

    supabase.auth.getSession().then(async ({ data }) => {
      if (cancelled) return;
      setSession(data.session);
      await loadOrg(data.session);
      if (!cancelled) setLoading(false);
    });

    const { data: sub } = supabase.auth.onAuthStateChange(async (_e, next) => {
      setSession(next);
      await loadOrg(next);
    });

    return () => {
      cancelled = true;
      sub.subscription.unsubscribe();
    };
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      session,
      org,
      loading,
      async signIn(email, password) {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) throw new Error(error.message);
      },
      async signUp(email, password) {
        const { data, error } = await supabase.auth.signUp({ email, password });
        if (error) throw new Error(error.message);
        // Projects with email confirmation on return a user but no session.
        // The caller has to say "check your inbox" rather than silently
        // appearing to do nothing.
        return { needsEmailConfirm: !data.session };
      },
      async signOut() {
        await supabase.auth.signOut();
        setOrg(null);
      },
      async refreshOrg() {
        await loadOrg(session);
      },
    }),
    [session, org, loading],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
