import { useEffect, useState } from "react";

import { api } from "../../lib/api";

/**
 * Interview ended — shown after either a complete or early-ended call.
 * Matches the neobrutalist theme.
 */

type InterviewStatus = "in_progress" | "completed" | "abandoned" | "flagged";

const TERMINAL_STATUSES = new Set<InterviewStatus>(["completed", "abandoned", "flagged"]);

export function InterviewComplete({ token }: { token?: string }) {
  const [status, setStatus] = useState<InterviewStatus>("in_progress");

  useEffect(() => {
    if (!token || TERMINAL_STATUSES.has(status)) return;

    let active = true;
    const refresh = async () => {
      try {
        const result = await api.interviewStatus<{ status: InterviewStatus }>(token);
        if (active) setStatus(result.status);
      } catch {
        // The call is already over; keep the safe processing message on transient failures.
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 2000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [status, token]);

  const completed = status === "completed";
  const abandoned = status === "abandoned";
  const flagged = status === "flagged";

  return (
    <main className="wrap narrow">
      <div className="nb-card" style={{ textAlign: "center" }}>
        <div
          style={{
            width: "3rem",
            height: "3rem",
            margin: "0 auto 1.5rem",
            borderRadius: "9999px",
            background: "color-mix(in srgb, var(--color-lime) 30%, var(--color-panel))",
            border: "var(--edge-w) solid var(--color-edge)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontSize: "1.5rem",
          }}
        >
          ✓
        </div>
        <h1 style={{ fontSize: "1.2rem", marginBottom: "0.5rem" }}>
          {completed ? "Interview complete" : "Call ended"}
        </h1>
        <p
          role="status"
          style={{ color: "var(--color-muted)", fontSize: "0.9rem", marginBottom: "1rem" }}
        >
          {completed
            ? "Your interview has been saved. Your recruiter will follow up with next steps."
            : abandoned
              ? "The interview ended early. Your captured responses were saved and marked incomplete."
              : flagged
                ? "Your captured responses were saved, but processing needs review. Your recruiter can follow up."
                : "Your captured responses are saved. We are processing the completed interview now."}
        </p>
        <p style={{ fontSize: "0.8rem", color: "var(--color-muted)" }}>
          You can close this window.
        </p>
      </div>
    </main>
  );
}
