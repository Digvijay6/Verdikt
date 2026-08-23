/**
 * Live transcript — shows agent and candidate turns as they happen.
 * Matches the neobrutalist theme.
 */

interface TranscriptEntry {
  speaker: "agent" | "candidate";
  text: string;
  questionId?: string;
}

interface LiveTranscriptProps {
  transcript: TranscriptEntry[];
}

export function LiveTranscript({ transcript }: LiveTranscriptProps) {
  if (transcript.length === 0) {
    return (
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", minHeight: "50vh", color: "var(--color-muted)", fontSize: "0.85rem" }}>
        The interview will begin shortly...
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1rem" }}>
      {transcript.map((entry, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            justifyContent: entry.speaker === "agent" ? "flex-start" : "flex-end",
          }}
        >
          <div
            className="nb-row"
            style={{
              maxWidth: "80%",
              background: entry.speaker === "agent" ? "var(--color-panel)" : "color-mix(in srgb, var(--color-lime) 12%, var(--color-panel))",
            }}
          >
            <div style={{ fontSize: "0.75rem", color: "var(--color-muted)", marginBottom: "0.25rem" }}>
              {entry.speaker === "agent" ? "Verdikt" : "You"}
            </div>
            <p style={{ fontSize: "0.9rem", lineHeight: 1.5, margin: 0 }}>
              {entry.text}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}