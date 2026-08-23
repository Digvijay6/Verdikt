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

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
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
  // Which user we last resolved an org for. See the auth listener below.
  const lastUserId = useRef<string | null | undefined>(undefined);

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
    const ready = () => {
      if (!cancelled) setLoading(false);
    };

    // supabase-js serialises token work behind a Web Lock, and getSession() can
    // block on it — another tab holding it, or one that died without releasing
    // it. Without a ceiling the app sits on "Loading..." indefinitely with
    // nothing on screen to say why. Falling through to signed-out is wrong but
    // recoverable; hanging is neither.
    const timer = setTimeout(() => {
      if (!cancelled) {
        console.warn("Session lookup did not settle in time; continuing.");
        ready();
      }
    }, 6000);

    supabase.auth
      .getSession()
      .then(async ({ data }) => {
        if (cancelled) return;
        setSession(data.session);
        lastUserId.current = data.session?.user?.id ?? null;
        await loadOrg(data.session);
      })
      // Without this, a rejection skips setLoading(false) entirely and the
      // spinner never clears.
      .catch((err) => console.error("Session lookup failed:", err))
      .finally(ready);

    const { data: sub } = supabase.auth.onAuthStateChange((_e, next) => {
      // Never await Supabase inside this callback. It runs while the auth lock
      // is held, and loadOrg -> api.get -> getSession() waits on that same
      // lock, which deadlocks: the callback never returns, the lock is never
      // released, and every later auth call queues behind it. Deferring by a
      // turn lets the lock go first.
      setTimeout(async () => {
        if (cancelled) return;
        setSession(next);

        // Only refetch the org when the *user* changes. TOKEN_REFRESHED fires
        // on a timer and on any getSession() that renews - and loadOrg calls
        // /auth/me, whose request() calls getSession(), so reloading on every
        // event feeds itself into a loop of auth/me calls. An org cannot change
        // without the user changing.
        const userId = next?.user?.id ?? null;
        if (userId !== lastUserId.current) {
          lastUserId.current = userId;
          await loadOrg(next);
        }
        ready();
      }, 0);
    });

    return () => {
      cancelled = true;
      clearTimeout(timer);
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
