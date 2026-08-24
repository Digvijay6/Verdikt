/**
 * Live transcript — shows agent and candidate turns as they happen.
 * Matches the neobrutalist theme.
 */

import { useEffect, useRef } from "react";

import type { TranscriptEntry } from "./transcript";

interface LiveTranscriptProps {
  transcript: TranscriptEntry[];
}

export function LiveTranscript({ transcript }: LiveTranscriptProps) {
  const endRef = useRef<HTMLDivElement>(null);
  const latestEntry = transcript.at(-1);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [latestEntry?.id, latestEntry?.text]);

  if (transcript.length === 0) {
    return (
      <section aria-labelledby="live-transcript-heading">
        <h2 id="live-transcript-heading" style={{ fontSize: "1rem", marginTop: 0 }}>
          Live transcript
        </h2>
        <div
          role="status"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            minHeight: "44vh",
            color: "var(--color-muted)",
            fontSize: "0.85rem",
          }}
        >
          Listening for the conversation...
        </div>
      </section>
    );
  }

  return (
    <section aria-labelledby="live-transcript-heading">
      <h2 id="live-transcript-heading" style={{ fontSize: "1rem", marginTop: 0 }}>
        Live transcript
      </h2>
      <div
        role="log"
        aria-live="polite"
        aria-relevant="additions text"
        style={{ display: "flex", flexDirection: "column", gap: "1rem" }}
      >
        {transcript.map((entry) => (
          <div
            key={entry.id}
            style={{
              display: "flex",
              justifyContent:
                entry.speaker === "agent" ? "flex-start" : "flex-end",
            }}
          >
            <div
              className="nb-row"
              style={{
                maxWidth: "80%",
                background:
                  entry.speaker === "agent"
                    ? "var(--color-panel)"
                    : "color-mix(in srgb, var(--color-lime) 12%, var(--color-panel))",
              }}
            >
              <div
                style={{
                  fontSize: "0.75rem",
                  color: "var(--color-muted)",
                  marginBottom: "0.25rem",
                }}
              >
                {entry.speaker === "agent" ? "Verdikt" : "You"}
              </div>
              <p style={{ fontSize: "0.9rem", lineHeight: 1.5, margin: 0 }}>
                {entry.text}
              </p>
            </div>
          </div>
        ))}
        <div ref={endRef} aria-hidden="true" />
      </div>
    </section>
  );
}
