import assert from "node:assert/strict";
import test from "node:test";

import { canEndCall } from "./endCall.ts";

test("requires confirmation before ending an incomplete interview", () => {
  const messages = [];

  assert.equal(canEndCall(false, (message) => (messages.push(message), false)), false);
  assert.match(messages[0], /submit this interview as incomplete/i);
});

test("ends a complete interview without confirmation", () => {
  let confirmations = 0;

  assert.equal(canEndCall(true, () => (++confirmations, false)), true);
  assert.equal(confirmations, 0);
});
