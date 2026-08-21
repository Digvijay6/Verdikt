import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import ApplicationForm from "./routes/intake/ApplicationForm";
import JobsPage from "./routes/intake/JobsPage";
import ReviewQueue from "./routes/intake/ReviewQueue";
import "./app.css";

const queryClient = new QueryClient();

/**
 * Route ownership mirrors folder ownership:
 *   /jobs, /applications        LANE 1  routes/intake
 *   /apply/:jobId               LANE 1  public — candidates applying
 *   /leaderboard, /candidates   LANE 3  routes/recruiter
 *   /interview/:token           LANE 2  public — the interview itself
 *
 * The two public routes are the only pages a candidate ever sees. Everything
 * else sits behind a Supabase session.
 */
export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Navigate to="/jobs" replace />} />

          {/* LANE 1 */}
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/applications/:jobId" element={<ReviewQueue />} />
          <Route path="/apply/:jobId" element={<ApplicationForm />} />

          {/* LANE 3 */}
          <Route path="/leaderboard/*" element={<Placeholder name="Leaderboard" />} />
          <Route path="/candidates/*" element={<Placeholder name="Candidate detail" />} />

          {/* LANE 2 — public */}
          <Route path="/interview/:token" element={<Placeholder name="Interview" />} />
        </Routes>
      </BrowserRouter>
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
