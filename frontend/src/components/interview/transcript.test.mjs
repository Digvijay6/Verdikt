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

test("merges adjacent fragments from the same speaker into one readable turn", () => {
  const entries = toTranscriptEntries(
    [
      {
        text: "I documented the trade-offs",
        participantInfo: { identity: "candidate-123" },
        streamInfo: { id: "candidate-1" },
      },
      {
        text: "and kept the rollout reversible",
        participantInfo: { identity: "candidate-123" },
        streamInfo: { id: "candidate-2" },
      },
      {
        text: "What did you measure?",
        participantInfo: { identity: "verdikt-agent" },
        streamInfo: { id: "agent-1" },
      },
    ],
    "candidate-123",
  );

  assert.deepEqual(entries, [
    {
      id: "candidate-1",
      speaker: "candidate",
      text: "I documented the trade-offs and kept the rollout reversible",
    },
    { id: "agent-1", speaker: "agent", text: "What did you measure?" },
  ]);
});

test("replaces an interim fragment when the same stream publishes fuller text", () => {
  const entries = toTranscriptEntries(
    [
      {
        text: "When deploy",
        participantInfo: { identity: "verdikt-agent" },
        streamInfo: { id: "agent-1" },
      },
      {
        text: "When deploying a service, what do you verify?",
        participantInfo: { identity: "verdikt-agent" },
        streamInfo: { id: "agent-1" },
      },
    ],
    "candidate-123",
  );

  assert.deepEqual(entries, [
    {
      id: "agent-1",
      speaker: "agent",
      text: "When deploying a service, what do you verify?",
    },
  ]);
});
