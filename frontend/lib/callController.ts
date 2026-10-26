// The call's state machine. No React and no DOM: socket, speaker and microphone are injected,
// so tests use fakes.
//
// Text, the bot's voice, the microphone, and talking over the bot.
//
// Interrupting: while the bot speaks the microphone keeps listening, more strictly. Speech
// then stops the bot and is recorded as a normal turn. The risk is the bot hearing its own
// voice through the speakers, so each interruption is checked against what the server
// heard: two "suspected echoes" in a row switch THIS call to no-interrupting (the mic is
// muted while the bot speaks). A real interruption resets the count.
//
// Safety rules:
// - Every call gets its own resources object; events from an older call are ignored.
// - One request in flight; the next `turn` or `error` answers it. An utterance finished
//   while waiting goes into a one-slot queue (the newest replaces an older one).
// - Releasing a call's resources is idempotent and never throws.
// - A new call starts from a completely fresh state.

import { describeClose, describeError, MESSAGES } from "./closeCodes";
import { BARGE_IN_DEFAULT } from "./config";
import { isSuspectedEcho } from "./echo";
import {
  EXPECTED_SAMPLE_RATE,
  bargeInMessage,
  hangupMessage,
  parseServerMessage,
  textMessage,
  type Decision,
  type Limits,
  type ServerMessage,
} from "./protocol";

export type CallStatus =
  | "idle"
  | "starting"
  | "listening"
  | "hearing"
  | "thinking"
  | "speaking"
  | "ending"
  | "ended"
  | "failed";

export type MicStatus = "off" | "requesting" | "on" | "blocked" | "unavailable";

export interface ConversationLine {
  id: number;
  speaker: "caller" | "bot";
  text: string;
}

export interface CallState {
  status: CallStatus;
  mic: MicStatus;
  lines: ConversationLine[];
  decision: Decision | null;
  notice: string | null;
  limits: Limits | null;
}

export interface SocketHandlers {
  onOpen(): void;
  onMessage(data: unknown): void;
  onClose(code: number): void;
  onError(): void;
}

export interface CallSocket {
  send(data: string | ArrayBuffer): void;
  close(): void;
  isOpen(): boolean;
}

export type SocketFactory = (url: string, handlers: SocketHandlers) => CallSocket;

export interface Speaker {
  /** Speak; call onDone when finished (not when cancelled). */
  speak(text: string, onDone: () => void): void;
  cancel(): void;
}

export interface RecorderEvents {
  onSpeechStart(): void;
  onSpeechDiscarded(): void;
  onUtterance(pcm: ArrayBuffer): void;
}

export interface Recorder {
  stop(): void;
  setMuted(muted: boolean): void;
  /** Keep listening while the bot speaks (strictly). guard: ignore its dying voice afterwards. */
  setBotSpeaking(speaking: boolean, guard: boolean): void;
  setMaxSeconds(seconds: number): void;
}

export type RecorderFactory = (events: RecorderEvents) => Promise<Recorder>;

export interface ControllerOptions {
  url: string;
  createSocket: SocketFactory;
  createSpeaker?: () => Speaker;
  createRecorder?: RecorderFactory;
  /** Let callers interrupt the bot. Default: BARGE_IN_DEFAULT. */
  bargeIn?: boolean;
  readyTimeoutMs?: number;
  maxInvalidMessages?: number;
}

export const INITIAL_STATE: CallState = {
  status: "idle",
  mic: "off",
  lines: [],
  decision: null,
  notice: null,
  limits: null,
};

const IN_CALL: ReadonlySet<CallStatus> = new Set(["starting", "listening", "hearing", "thinking", "speaking"]);
const CAN_TYPE: ReadonlySet<CallStatus> = new Set(["listening", "hearing", "speaking"]);
const MIC_OPEN: ReadonlySet<CallStatus> = new Set(["listening", "hearing", "thinking"]);
const DEFAULT_READY_TIMEOUT_MS = 10_000;
const DEFAULT_MAX_INVALID = 3;
const MAX_UTTERANCE_SECONDS = 25;
const UTTERANCE_MARGIN_SECONDS = 2; // stay under the server's limit

/** Speaks nothing and finishes at once (tests, or no speech synthesis). */
export const silentSpeaker = (): Speaker => ({
  speak: (_text, onDone) => onDone(),
  cancel: () => {},
});

/** Everything belonging to one call. Replaced (never reused) when a new call starts. */
interface Call {
  socket: CallSocket | null;
  speaker: Speaker;
  recorder: Recorder | null;
  readyTimer: ReturnType<typeof setTimeout> | null;
  ready: boolean;
  inFlight: boolean;
  queued: ArrayBuffer | null;
  maxSeconds: number;
  /** What the bot is saying right now (to compare an interruption with it). */
  speakingReply: string | null;
  /** An interruption not yet judged: waiting for what the server heard. */
  bargeIn: { reply: string } | null;
  /** Suspected echoes in a row. */
  echoStrikes: number;
  /** This call no longer allows interrupting (echo was detected). */
  halfDuplex: boolean;
  /** The next unmute happens because the bot finished: ignore its voice dying away. */
  guardOnUnmute: boolean;
  endedByServer: boolean;
  invalidMessages: number;
  released: boolean;
}

export function isInCall(status: CallStatus): boolean {
  return IN_CALL.has(status);
}

export function canType(status: CallStatus): boolean {
  return CAN_TYPE.has(status);
}

function isPermissionError(error: unknown): boolean {
  const name = (error as { name?: unknown } | null)?.name;
  return name === "NotAllowedError" || name === "SecurityError";
}

export class CallController {
  private state: CallState = INITIAL_STATE;
  private readonly listeners = new Set<() => void>();
  private call: Call | null = null;
  private nextLineId = 1;

  constructor(private readonly options: ControllerOptions) {}

  // -- store interface (useSyncExternalStore) -------------------------------------------

  getState = (): CallState => this.state;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  // -- commands ---------------------------------------------------------------------------

  start(): void {
    if (isInCall(this.state.status) || this.state.status === "ending") return;
    const call: Call = {
      socket: null,
      speaker: (this.options.createSpeaker ?? silentSpeaker)(),
      recorder: null,
      readyTimer: null,
      ready: false,
      inFlight: false,
      queued: null,
      maxSeconds: MAX_UTTERANCE_SECONDS,
      speakingReply: null,
      bargeIn: null,
      echoStrikes: 0,
      halfDuplex: false, // every call starts with interrupting allowed
      guardOnUnmute: false,
      endedByServer: false,
      invalidMessages: 0,
      released: false,
    };
    this.call = call;
    // nothing from the previous call survives
    this.set({ ...INITIAL_STATE, status: "starting", mic: this.options.createRecorder ? "requesting" : "off" });
    call.readyTimer = setTimeout(
      () => this.fail(call, MESSAGES.couldNotConnect),
      this.options.readyTimeoutMs ?? DEFAULT_READY_TIMEOUT_MS,
    );
    try {
      call.socket = this.options.createSocket(this.options.url, {
        onOpen: () => {},
        onMessage: (data) => this.onMessage(call, data),
        onClose: (code) => this.onClose(call, code),
        onError: () => {}, // a close event always follows an error
      });
    } catch {
      this.fail(call, MESSAGES.couldNotConnect);
      return;
    }
    this.startMicrophone(call);
  }

  /** Send a typed message. Returns false when it was not sent (text is never queued). */
  sendText(text: string): boolean {
    const call = this.call;
    if (!call || !this.isCurrent(call) || !canType(this.state.status) || call.inFlight) return false;
    const clean = text.trim();
    if (!clean) return false;
    const limit = this.state.limits?.maxTextChars ?? Number.POSITIVE_INFINITY;
    if (clean.length > limit) {
      this.set({ notice: MESSAGES.tooLong });
      return false;
    }
    if (!call.socket?.isOpen()) return false;
    call.speaker.cancel(); // typing while the bot talks: stop talking
    call.speakingReply = null;
    call.bargeIn = null; // an interruption we can no longer judge
    call.guardOnUnmute = true;
    call.socket.send(textMessage(clean));
    call.inFlight = true;
    this.set({ lines: this.withLine("caller", clean), status: "thinking", notice: null });
    return true;
  }

  /** End the call (End button). Repeated calls do nothing. */
  end(): void {
    const call = this.call;
    if (!call || !this.isCurrent(call) || !isInCall(this.state.status)) return;
    this.set({ status: "ending" });
    if (call.ready && call.socket?.isOpen()) {
      try {
        call.socket.send(hangupMessage());
      } catch {
        // the socket is going away anyway
      }
    }
    this.finish(call, "ended", MESSAGES.callEnded);
  }

  /** Component unmount or page hide: end an active call and release everything. */
  shutdown(): void {
    if (isInCall(this.state.status)) {
      this.end();
      return;
    }
    if (this.call) this.release(this.call);
  }

  // -- microphone -------------------------------------------------------------------------

  private startMicrophone(call: Call): void {
    const create = this.options.createRecorder;
    if (!create) return;
    let pending: Promise<Recorder>;
    try {
      pending = create({
        onSpeechStart: () => this.onSpeechStart(call),
        onSpeechDiscarded: () => this.onSpeechDiscarded(call),
        onUtterance: (pcm) => this.onUtterance(call, pcm),
      });
    } catch (error) {
      pending = Promise.reject(error);
    }
    pending.then(
      (recorder) => {
        if (!this.isCurrent(call)) {
          safely(() => recorder.stop()); // the call ended while we waited for the mic
          return;
        }
        call.recorder = recorder;
        recorder.setMaxSeconds(call.maxSeconds);
        this.applyMicMode(call);
        this.set({ mic: "on" });
      },
      (error: unknown) => {
        if (!this.isCurrent(call)) return;
        const blocked = isPermissionError(error);
        this.set({
          mic: blocked ? "blocked" : "unavailable",
          notice: blocked ? MESSAGES.micBlocked : MESSAGES.micUnavailable,
        });
      },
    );
  }

  private stopMicrophone(call: Call, mic: MicStatus): void {
    const recorder = call.recorder;
    call.recorder = null;
    call.queued = null;
    if (recorder) safely(() => recorder.stop());
    this.set({ mic });
  }

  private onSpeechStart(call: Call): void {
    if (!this.isCurrent(call)) return;
    if (this.state.status === "listening") {
      this.set({ status: "hearing" });
    } else if (this.state.status === "speaking" && this.interruptible(call)) {
      this.interrupt(call);
    }
  }

  private onSpeechDiscarded(call: Call): void {
    if (!this.isCurrent(call)) return;
    if (call.bargeIn) {
      // We stopped the bot for something too short to be a sentence: noise or echo.
      call.bargeIn = null;
      this.countEcho(call);
    }
    if (this.state.status === "hearing") this.set({ status: "listening" });
  }

  private interruptible(call: Call): boolean {
    return (this.options.bargeIn ?? BARGE_IN_DEFAULT) && !call.halfDuplex && call.recorder !== null;
  }

  /** The caller started talking over the bot: stop the bot and listen. */
  private interrupt(call: Call): void {
    call.bargeIn = { reply: call.speakingReply ?? "" };
    call.speakingReply = null;
    call.guardOnUnmute = false; // the caller is speaking right now: don't ignore them
    safely(() => call.speaker.cancel());
    if (call.socket?.isOpen()) safely(() => call.socket?.send(bargeInMessage()));
    this.set({ status: "hearing" });
  }

  /** Judge an interruption once we know what the server heard (empty text = nothing usable). */
  private judgeInterruption(call: Call, heard: string): void {
    const pending = call.bargeIn;
    if (!pending) return;
    call.bargeIn = null;
    if (isSuspectedEcho(heard, pending.reply)) this.countEcho(call);
    else call.echoStrikes = 0; // a real person: the earlier suspicions were wrong
  }

  private countEcho(call: Call): void {
    call.echoStrikes += 1;
    if (call.echoStrikes >= 2 && !call.halfDuplex) {
      call.halfDuplex = true;
      this.applyMicMode(call);
      this.set({ notice: MESSAGES.echoOff });
    }
  }

  /** Mute, listen strictly, or listen normally, depending on what the bot is doing. */
  private applyMicMode(call: Call): void {
    const recorder = call.recorder;
    if (!recorder || call.released) return;
    const status = this.state.status;
    safely(() => {
      if (MIC_OPEN.has(status)) {
        recorder.setMuted(false);
        recorder.setBotSpeaking(false, call.guardOnUnmute);
        call.guardOnUnmute = false;
      } else if (status === "speaking" && this.interruptible(call)) {
        recorder.setMuted(false);
        recorder.setBotSpeaking(true, false);
      } else {
        recorder.setMuted(true); // no interrupting: never listen to our own voice
      }
    });
  }

  private onUtterance(call: Call, pcm: ArrayBuffer): void {
    if (!this.isCurrent(call)) return;
    const status = this.state.status;
    if ((status === "listening" || status === "hearing") && !call.inFlight) {
      this.sendAudio(call, pcm);
    } else if (call.inFlight) {
      call.queued = pcm; // one slot: the newest replaces an older one
    }
    // otherwise (bot speaking, call ending): dropped
  }

  private sendAudio(call: Call, pcm: ArrayBuffer): void {
    if (!call.socket?.isOpen()) return;
    call.socket.send(pcm);
    call.inFlight = true;
    this.set({ status: "thinking", notice: null });
  }

  private sendQueued(call: Call): void {
    const pcm = call.queued;
    call.queued = null;
    if (pcm && !call.inFlight && this.isCurrent(call)) this.sendAudio(call, pcm);
  }

  // -- server events ----------------------------------------------------------------------

  private onMessage(call: Call, data: unknown): void {
    if (!this.isCurrent(call)) return; // late message from an earlier call
    const parsed = parseServerMessage(data);
    if (!parsed.ok) {
      this.countInvalid(call);
      return;
    }
    this.handle(call, parsed.message);
  }

  private handle(call: Call, message: ServerMessage): void {
    switch (message.type) {
      case "ready":
        if (call.ready) return;
        if (message.sampleRate !== EXPECTED_SAMPLE_RATE) {
          this.fail(call, MESSAGES.generic);
          return;
        }
        call.ready = true;
        this.clearReadyTimer(call);
        call.maxSeconds = Math.min(
          MAX_UTTERANCE_SECONDS,
          message.limits.maxUtteranceSeconds - UTTERANCE_MARGIN_SECONDS,
        );
        call.recorder?.setMaxSeconds(call.maxSeconds);
        this.set({ limits: message.limits });
        return;
      case "turn":
        if (!call.ready) {
          this.countInvalid(call); // a turn before ready breaks the protocol
          return;
        }
        this.onTurn(call, message);
        return;
      case "transcript":
        // What the server heard. Noise gives an empty transcript: no caller line.
        this.judgeInterruption(call, message.text);
        if (message.text.trim()) this.set({ lines: this.withLine("caller", message.text) });
        return;
      case "error":
        call.inFlight = false; // an error answers the request in flight
        call.bargeIn = null; // nothing was heard, so there is no evidence either way
        if (message.code === "stt_unavailable") this.stopMicrophone(call, "unavailable");
        this.set({
          notice: describeError(message.code),
          status: this.state.status === "thinking" ? "listening" : this.state.status,
        });
        this.sendQueued(call);
        return;
      case "closing":
        this.set({ notice: MESSAGES.restarting });
        return;
    }
  }

  private onTurn(call: Call, turn: Extract<ServerMessage, { type: "turn" }>): void {
    call.inFlight = false;
    this.judgeInterruption(call, ""); // a turn with no transcript before it: nothing was heard
    const lines = turn.reply ? this.withLine("bot", turn.reply) : this.state.lines;
    if (turn.ended) {
      call.endedByServer = true;
      this.set({ lines, decision: turn.decision });
      if (turn.reply) call.speaker.speak(turn.reply, () => {}); // the goodbye is still spoken
      this.finish(call, "ended", MESSAGES.callEnded, { keepSpeech: true });
      return;
    }
    // Also covers the greeting and turns nobody asked for (the server's idle check).
    this.set({ lines, decision: turn.decision });
    if (turn.reply) {
      call.speakingReply = turn.reply;
      this.set({ status: "speaking" });
      call.speaker.speak(turn.reply, () => this.afterSpeaking(call));
    } else {
      this.afterSpeaking(call);
    }
  }

  private afterSpeaking(call: Call): void {
    if (!this.isCurrent(call)) return;
    call.speakingReply = null;
    call.guardOnUnmute = true; // the bot finished: ignore its voice dying away
    this.set({ status: call.inFlight ? "thinking" : "listening" });
    this.sendQueued(call);
  }

  private onClose(call: Call, code: number): void {
    if (!this.isCurrent(call)) return;
    const notice = describeClose(code, { ready: call.ready, endedByServer: call.endedByServer });
    this.finish(call, call.ready ? "ended" : "failed", notice);
  }

  // -- helpers ----------------------------------------------------------------------------

  private isCurrent(call: Call): boolean {
    return call === this.call && !call.released;
  }

  private countInvalid(call: Call): void {
    call.invalidMessages += 1;
    if (call.invalidMessages >= (this.options.maxInvalidMessages ?? DEFAULT_MAX_INVALID)) {
      this.fail(call, MESSAGES.generic);
    }
  }

  private fail(call: Call, notice: string): void {
    if (!this.isCurrent(call)) return;
    this.finish(call, "failed", notice);
  }

  private finish(
    call: Call,
    status: "ended" | "failed",
    notice: string,
    { keepSpeech = false }: { keepSpeech?: boolean } = {},
  ): void {
    this.release(call, keepSpeech);
    this.set({ status, notice, mic: "off" });
  }

  private clearReadyTimer(call: Call): void {
    if (call.readyTimer !== null) {
      clearTimeout(call.readyTimer);
      call.readyTimer = null;
    }
  }

  /** Free everything this call holds. Safe to call any number of times; never throws. */
  private release(call: Call, keepSpeech = false): void {
    if (call.released) return;
    call.released = true;
    call.inFlight = false;
    call.queued = null;
    this.clearReadyTimer(call);
    const recorder = call.recorder;
    call.recorder = null;
    if (recorder) safely(() => recorder.stop()); // mic tracks, audio nodes, AudioContext
    if (!keepSpeech) safely(() => call.speaker.cancel());
    const socket = call.socket;
    call.socket = null;
    if (socket) safely(() => socket.close());
  }

  private withLine(speaker: ConversationLine["speaker"], text: string): ConversationLine[] {
    return [...this.state.lines, { id: this.nextLineId++, speaker, text }];
  }

  private set(patch: Partial<CallState>): void {
    this.state = { ...this.state, ...patch };
    const call = this.call;
    if (patch.status && call) this.applyMicMode(call);
    for (const listener of this.listeners) listener();
  }
}

function safely(action: () => void): void {
  try {
    action();
  } catch {
    // cleanup must never throw
  }
}
