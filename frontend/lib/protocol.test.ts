import { describe, expect, it } from "vitest";

import fixtures from "./__fixtures__/backend-messages.json";
import { hangupMessage, parseServerMessage, textMessage, type ServerMessage } from "./protocol";

// The fixtures were captured from the real backend (/ws/call through Starlette's TestClient).

const raw = (value: unknown): string => JSON.stringify(value);

function parsed(value: unknown): ServerMessage {
  const result = parseServerMessage(raw(value));
  if (!result.ok) throw new Error(`rejected: ${result.problem}`);
  return result.message;
}

const BACKEND_MESSAGES = [
  "ready",
  "greeting_turn",
  "text_turn",
  "hangup_turn",
  "audio_transcript",
  "audio_turn",
  "short_audio_turn",
  "idle_turn",
  "error_bad_json",
  "error_stt_unavailable",
  "closing",
] as const;

describe("messages from the real backend", () => {
  it.each(BACKEND_MESSAGES)("accepts %s", (key) => {
    expect(parseServerMessage(raw(fixtures[key])).ok).toBe(true);
  });

  it("reads the limits as numbers even though they arrive as floats", () => {
    expect(parsed(fixtures.ready)).toEqual({
      type: "ready",
      sessionId: fixtures.ready.session_id,
      sampleRate: 16000,
      limits: { maxTextChars: 500, maxUtteranceSeconds: 30 },
    });
  });

  it("keeps only the approved decision fields of a turn", () => {
    const turn = parsed(fixtures.text_turn);
    expect(Object.keys(turn).sort()).toEqual(
      ["decision", "ended", "reply", "source", "transcript", "turn", "type"].sort(),
    );
    if (turn.type !== "turn") throw new Error("not a turn");
    expect(Object.keys(turn.decision).sort()).toEqual(["actions", "intent", "phaseFrom", "phaseTo", "reason"]);
    expect(turn.decision.intent).toBe("faq_hours");
    // nothing else from the trace or the state is carried into the page
    const text = JSON.stringify(turn);
    for (const dropped of ["entities", "slot_changes", "normalized", "slots", "ranked_intents"]) {
      expect(text).not.toContain(dropped);
    }
  });

  it("knows the audio order: transcript first, then the turn", () => {
    expect(parsed(fixtures.audio_transcript)).toEqual({ type: "transcript", text: "what are your timings" });
    expect(parsed(fixtures.audio_turn)).toMatchObject({ type: "turn", source: "audio" });
  });

  it("accepts a short-audio turn that comes without a transcript", () => {
    expect(parsed(fixtures.short_audio_turn)).toMatchObject({ type: "turn", source: "audio", transcript: "" });
  });

  it("accepts the unprompted idle turn", () => {
    expect(parsed(fixtures.idle_turn)).toMatchObject({ type: "turn", source: "text", transcript: "" });
  });

  it("drops the server's error text and keeps only the code", () => {
    expect(parsed(fixtures.error_bad_json)).toEqual({ type: "error", code: "bad_json" });
  });

  it("records the close codes the backend actually uses", () => {
    expect(fixtures.hangup_close_code).toBe(1000);
    expect(fixtures.busy_close_code).toBe(1013);
  });
});

describe("rejects anything unexpected", () => {
  const ready = fixtures.ready;
  const turn = fixtures.text_turn;

  it.each([
    ["binary data", new ArrayBuffer(4)],
    ["not JSON", "{"],
    ["a JSON array", "[]"],
    ["a JSON string", '"turn"'],
    ["no type", raw({ text: "hi" })],
    ["an unknown type", raw({ type: "surprise" })],
    ["ready without limits", raw({ ...ready, limits: undefined })],
    ["ready with a text sample rate", raw({ ...ready, sample_rate: "16000" })],
    ["ready with a missing limit", raw({ ...ready, limits: { max_text_chars: 500 } })],
    ["a turn with a text 'ended'", raw({ ...turn, ended: "yes" })],
    ["a turn with an unknown source", raw({ ...turn, source: "telepathy" })],
    ["a turn without a trace", raw({ ...turn, trace: undefined })],
    ["a turn without a state", raw({ ...turn, state: undefined })],
    ["a turn whose actions are not text", raw({ ...turn, trace: { ...turn.trace, actions: [1] } })],
    ["a turn with a missing reason", raw({ ...turn, trace: { ...turn.trace, reason: null } })],
    ["a transcript without text", raw({ type: "transcript", text: 3 })],
    ["an error without a code", raw({ type: "error", message: "boom" })],
    ["closing without a reason", raw({ type: "closing" })],
  ])("%s", (_label, value) => {
    expect(parseServerMessage(value).ok).toBe(false);
  });

  it("ignores extra fields instead of copying them", () => {
    const message = parsed({ ...ready, surprise: "<script>", limits: { ...ready.limits, extra: 1 } });
    expect(JSON.stringify(message)).not.toContain("surprise");
    expect(JSON.stringify(message)).not.toContain("extra");
  });
});

describe("messages the page sends", () => {
  it("builds the text and hangup messages the backend expects", () => {
    expect(JSON.parse(textMessage("table for two"))).toEqual({ type: "text", text: "table for two" });
    expect(JSON.parse(hangupMessage())).toEqual({ type: "hangup" });
  });
});
