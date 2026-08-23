import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  BrowserRouter,
  Link,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";

import { AuthProvider, useAuth } from "./lib/auth";
import ApplicationForm from "./routes/intake/ApplicationForm";
import JobsPage from "./routes/intake/JobsPage";
import ReviewQueue from "./routes/intake/ReviewQueue";
import Login from "./routes/auth/Login";
import Onboarding from "./routes/auth/Onboarding";
import Signup from "./routes/auth/Signup";
import "./app.css";

import InterviewRoom from "./routes/interview/InterviewRoom";

const queryClient = new QueryClient();

/**
 * Being signed in and having a company are separate conditions, and the guard
 * treats them separately. Someone who has just signed up is authenticated with
 * no organization — normal, not broken — and belongs on onboarding rather than
 * staring at an empty dashboard.
 */
function RequireOrg({ children }: { children: React.ReactNode }) {
  const { session, org, loading } = useAuth();
  const location = useLocation();

  // Redirecting before the session has loaded bounces people who are already
  // signed in straight back to the login page on every refresh.
  if (loading) return <main className="wrap">Loading...</main>;
  if (!session)
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (!org) return <Navigate to="/onboarding" replace />;

  return <>{children}</>;
}

function Header() {
  const { session, org, signOut } = useAuth();
  if (!session) return null;
  return (
    <header className="topbar">
      <Link to="/jobs" className="brand">
        Verdikt
      </Link>
      <span className="hint">{org?.name}</span>
      <button onClick={() => void signOut()}>Sign out</button>
    </header>
  );
}

/**
 * Route ownership mirrors folder ownership:
 *   /login, /signup, /onboarding   LANE 1  routes/auth
 *   /jobs, /applications           LANE 1  routes/intake
 *   /apply/:jobId                  LANE 1  public - candidates applying
 *   /leaderboard, /candidates      LANE 3  routes/recruiter
 *   /interview/:token              LANE 2  public - the interview itself
 *
 * The two public candidate routes sit outside the guard deliberately: an
 * applicant has no account and never will.
 */
export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Header />
          <Routes>
            <Route path="/" element={<Navigate to="/jobs" replace />} />

            <Route path="/login" element={<Login />} />
            <Route path="/signup" element={<Signup />} />
            <Route path="/onboarding" element={<Onboarding />} />

            {/* LANE 1 */}
            <Route
              path="/jobs"
              element={
                <RequireOrg>
                  <JobsPage />
                </RequireOrg>
              }
            />
            <Route
              path="/applications/:jobId"
              element={
                <RequireOrg>
                  <ReviewQueue />
                </RequireOrg>
              }
            />

            {/* Public - no account, ever */}
            <Route path="/apply/:jobId" element={<ApplicationForm />} />
            <Route path="/interview/:token" element={<InterviewRoom />} />

            {/* LANE 3 */}
            <Route
              path="/leaderboard/*"
              element={
                <RequireOrg>
                  <Placeholder name="Leaderboard" />
                </RequireOrg>
              }
            />
            <Route
              path="/candidates/*"
              element={
                <RequireOrg>
                  <Placeholder name="Candidate detail" />
                </RequireOrg>
              }
            />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}

function Placeholder({ name }: { name: string }) {
  return (
    <main className="wrap">
      <h1>{name}</h1>
      <p className="hint">Not built yet.</p>
    </main>
  );
}
