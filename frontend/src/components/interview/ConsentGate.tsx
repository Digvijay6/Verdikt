/**
 * Consent gate — shown before the candidate joins the interview.
 * Matches the neobrutalist theme.
 */

interface ConsentGateProps {
  onAccept: () => void;
  error?: string | null;
}

export function ConsentGate({ onAccept, error }: ConsentGateProps) {
  return (
    <main className="wrap narrow">
      <div className="nb-card">
        <h1 style={{ fontSize: "1.3rem", marginBottom: "1rem" }}>
          Before we begin
        </h1>

        <div style={{ display: "flex", flexDirection: "column", gap: "0.8rem", fontSize: "0.9rem", color: "var(--color-muted)" }}>
          <p>
            This interview is conducted by an AI interviewer. Your voice will be
            recorded, transcribed, and analysed to produce a score for the
            recruiter.
          </p>

          <div style={{ borderLeft: "2px solid var(--color-line)", paddingLeft: "0.8rem", display: "flex", flexDirection: "column", gap: "0.4rem" }}>
            <p><strong>What we record:</strong> Audio of the interview conversation.</p>
            <p><strong>What we analyse:</strong> Your answers against a scoring rubric.</p>
            <p><strong>How long we keep it:</strong> Audio for 90 days, transcripts and scores for 12 months.</p>
            <p><strong>Your rights:</strong> You can request deletion of your data at any time by contacting the recruiter.</p>
          </div>

          <p style={{ color: "var(--color-muted)" }}>
            By clicking "Start interview" you consent to the above. You can
            withdraw at any point during the interview by ending the call.
          </p>
        </div>

        {error && (
          <p style={{ color: "var(--color-danger)", marginTop: "1rem", fontSize: "0.85rem" }}>
            {error}
          </p>
        )}

        <button
          onClick={onAccept}
          className="nb-btn"
          style={{ marginTop: "1.5rem", width: "100%", textAlign: "center" }}
        >
          Start interview
        </button>
      </div>
    </main>
  );
}