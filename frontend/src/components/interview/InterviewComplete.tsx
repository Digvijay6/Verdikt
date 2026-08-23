/**
 * Interview complete — shown when the interview ends.
 * Matches the neobrutalist theme.
 */

export function InterviewComplete() {
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
          Interview complete
        </h1>
        <p style={{ color: "var(--color-muted)", fontSize: "0.9rem", marginBottom: "1rem" }}>
          Thank you for your time. Your recruiter will follow up with next steps.
        </p>
        <p style={{ fontSize: "0.8rem", color: "var(--color-muted)" }}>
          You can close this window.
        </p>
      </div>
    </main>
  );
}