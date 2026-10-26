// Messages exchanged with the backend's /ws/call (see backend/app/api/schemas.py).
// Every server message is validated at runtime, and only the fields the page uses are kept:
// unknown fields are dropped, and of the trace only the five approved decision fields survive.

export type TurnSource = "greeting" | "text" | "audio";

export interface Limits {
  maxTextChars: number;
  maxUtteranceSeconds: number;
}

/** The part of a turn's sanitized trace the page may show. Nothing else is kept. */
export interface Decision {
  intent: string;
  phaseFrom: string;
  phaseTo: string;
  actions: string[];
  reason: string;
}

export type ServerMessage =
  | { type: "ready"; sessionId: string; sampleRate: number; limits: Limits }
  | {
      type: "turn";
      turn: number;
      reply: string;
      ended: boolean;
      transcript: string;
      source: TurnSource;
      decision: Decision;
    }
  | { type: "transcript"; text: string }
  | { type: "error"; code: string }
  | { type: "closing"; reason: string };

export type ParseResult = { ok: true; message: ServerMessage } | { ok: false; problem: string };

type JsonObject = Record<string, unknown>;

const isObject = (value: unknown): value is JsonObject =>
  typeof value === "object" && value !== null && !Array.isArray(value);
const isString = (value: unknown): value is string => typeof value === "string";
const isNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const isBoolean = (value: unknown): value is boolean => typeof value === "boolean";
const isStringList = (value: unknown): value is string[] => Array.isArray(value) && value.every(isString);
const SOURCES: readonly TurnSource[] = ["greeting", "text", "audio"];
const isSource = (value: unknown): value is TurnSource => SOURCES.includes(value as TurnSource);

const invalid = (problem: string): ParseResult => ({ ok: false, problem });
const valid = (message: ServerMessage): ParseResult => ({ ok: true, message });

function parseReady(data: JsonObject): ParseResult {
  const { session_id: sessionId, sample_rate: sampleRate, limits } = data;
  if (!isString(sessionId) || !isNumber(sampleRate) || !isObject(limits)) return invalid("bad ready");
  const { max_text_chars: maxTextChars, max_utterance_seconds: maxUtteranceSeconds } = limits;
  if (!isNumber(maxTextChars) || !isNumber(maxUtteranceSeconds)) return invalid("bad limits");
  return valid({ type: "ready", sessionId, sampleRate, limits: { maxTextChars, maxUtteranceSeconds } });
}

function parseDecision(trace: unknown): Decision | null {
  if (!isObject(trace)) return null;
  const { intent, phase_from: phaseFrom, phase_to: phaseTo, actions, reason } = trace;
  if (!isString(intent) || !isString(phaseFrom) || !isString(phaseTo) || !isString(reason)) return null;
  if (!isStringList(actions)) return null;
  return { intent, phaseFrom, phaseTo, actions: [...actions], reason };
}

function parseTurn(data: JsonObject): ParseResult {
  const { turn, reply, ended, transcript, source, trace, state } = data;
  if (!isNumber(turn) || !isString(reply) || !isBoolean(ended) || !isString(transcript)) return invalid("bad turn");
  if (!isSource(source) || !isObject(state)) return invalid("bad turn");
  const decision = parseDecision(trace);
  if (decision === null) return invalid("bad trace");
  return valid({ type: "turn", turn, reply, ended, transcript, source, decision });
}

/** Parse one WebSocket frame from the server. Never throws. */
export function parseServerMessage(raw: unknown): ParseResult {
  if (!isString(raw)) return invalid("not text");
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return invalid("not JSON");
  }
  if (!isObject(data)) return invalid("not an object");
  switch (data.type) {
    case "ready":
      return parseReady(data);
    case "turn":
      return parseTurn(data);
    case "transcript":
      return isString(data.text) ? valid({ type: "transcript", text: data.text }) : invalid("bad transcript");
    case "error":
      return isString(data.code) ? valid({ type: "error", code: data.code }) : invalid("bad error");
    case "closing":
      return isString(data.reason) ? valid({ type: "closing", reason: data.reason }) : invalid("bad closing");
    default:
      return invalid("unknown type");
  }
}

// -- messages the page sends --------------------------------------------------------------

export const textMessage = (text: string): string => JSON.stringify({ type: "text", text });
export const hangupMessage = (): string => JSON.stringify({ type: "hangup" });
export const bargeInMessage = (): string => JSON.stringify({ type: "barge_in" });

/** The audio format the backend expects (ready.sample_rate). */
export const EXPECTED_SAMPLE_RATE = 16_000;
