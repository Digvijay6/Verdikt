import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Route, Routes } from "react-router-dom";

const queryClient = new QueryClient();

/**
 * Route ownership mirrors folder ownership:
 *   /jobs, /applications   LANE 1  routes/intake
 *   /leaderboard, /candidates   LANE 3  routes/recruiter
 *   /interview/:token      LANE 2  routes/interview   (public, no auth)
 *
 * The interview route is the only public one. Everything else sits behind a
 * Supabase session.
 */
export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Placeholder name="Verdikt" />} />

          {/* LANE 1 */}
          <Route path="/jobs/*" element={<Placeholder name="Jobs" />} />
          <Route path="/applications/*" element={<Placeholder name="Applications" />} />

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
  return <div style={{ padding: 32, fontFamily: "system-ui" }}>{name}</div>;
}
