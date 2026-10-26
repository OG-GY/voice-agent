import { describe, expect, it } from "vitest";

import { describeClose, describeError, MESSAGES } from "./closeCodes";

const beforeReady = { ready: false, endedByServer: false };
const afterReady = { ready: true, endedByServer: false };

describe("close codes", () => {
  it.each([
    [1000, afterReady, MESSAGES.endedByServer],
    [1001, afterReady, MESSAGES.restarting],
    [1012, afterReady, MESSAGES.restarting],
    [1013, beforeReady, MESSAGES.busy], // the call limit closes after accept, before ready
    [1008, afterReady, MESSAGES.policy],
    [1009, afterReady, MESSAGES.tooLarge],
    [1011, afterReady, MESSAGES.serverError],
    [1006, beforeReady, MESSAGES.couldNotConnect], // includes origin/TLS refusals: no guessing
    [1006, afterReady, MESSAGES.disconnected],
    [4999, afterReady, MESSAGES.disconnected],
  ] as const)("%i -> the right message", (code, context, expected) => {
    expect(describeClose(code, context)).toBe(expected);
  });

  it.each([
    [1006, afterReady],
    [1011, afterReady],
    [1001, afterReady],
    [1012, afterReady],
  ] as const)("tells the caller about the callback when an established call is lost (%i)", (code, context) => {
    const message = describeClose(code, context);
    expect(message).toContain("call you back in 2-3 minutes");
    expect(message).toContain("confirm your reservation");
  });

  it("does not promise a callback when the call never started", () => {
    expect(describeClose(1006, beforeReady)).not.toContain("call you back");
    expect(describeClose(1013, beforeReady)).not.toContain("call you back");
  });

  it("says 'call ended' whenever the server ended the call", () => {
    expect(describeClose(1000, { ready: true, endedByServer: true })).toBe(MESSAGES.callEnded);
  });
});

describe("error codes", () => {
  it.each([
    ["stt_unavailable", MESSAGES.sttUnavailable],
    ["stt_busy", MESSAGES.sayAgain],
    ["stt_timeout", MESSAGES.sayAgain],
    ["rate_limited", MESSAGES.slowDown],
    ["text_too_long", MESSAGES.tooLong],
    ["audio_too_long", MESSAGES.tooLong],
    ["audio_invalid", MESSAGES.generic],
    ["bad_json", MESSAGES.generic],
    ["unknown_type", MESSAGES.generic],
    ["service_unavailable", MESSAGES.generic],
    ["something_new", MESSAGES.generic],
  ])("%s", (code, expected) => {
    expect(describeError(code)).toBe(expected);
  });
});
