import assert from "node:assert/strict";
import test from "node:test";

import { toTranscriptEntries } from "./transcript.ts";

test("maps LiveKit agent and candidate transcription messages for display", () => {
  const entries = toTranscriptEntries(
    [
      {
        text: "Welcome to the interview.",
        participantInfo: { identity: "verdikt-agent" },
        streamInfo: { id: "agent-1" },
      },
      {
        text: "Thank you. I am ready.",
        participantInfo: { identity: "candidate-123" },
        streamInfo: { id: "candidate-1" },
      },
    ],
    "candidate-123",
  );

  assert.deepEqual(entries, [
    { id: "agent-1", speaker: "agent", text: "Welcome to the interview." },
    { id: "candidate-1", speaker: "candidate", text: "Thank you. I am ready." },
  ]);
});

test("ignores blank interim transcriptions", () => {
  const entries = toTranscriptEntries(
    [
      {
        text: "   ",
        participantInfo: { identity: "verdikt-agent" },
        streamInfo: { id: "agent-1" },
      },
    ],
    "candidate-123",
  );

  assert.deepEqual(entries, []);
});
