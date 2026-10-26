import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import fixtures from "./__fixtures__/backend-messages.json";
import {
  CallController,
  type CallSocket,
  type Recorder,
  type RecorderEvents,
  type SocketHandlers,
  type Speaker,
} from "./callController";
import { MESSAGES } from "./closeCodes";

/** A socket the test drives by hand. */
class FakeSocket implements CallSocket {
  sent: unknown[] = [];
  closeCalls = 0;
  open = false;
  failOnClose = false;

  constructor(readonly handlers: SocketHandlers) {}

  send(data: string | ArrayBuffer): void {
    this.sent.push(typeof data === "string" ? JSON.parse(data) : { audioBytes: data.byteLength });
  }

  close(): void {
    this.closeCalls += 1;
    this.open = false;
    if (this.failOnClose) throw new Error("already gone");
  }

  isOpen(): boolean {
    return this.open;
  }

  // test drivers
  connect(): void {
    this.open = true;
    this.handlers.onOpen();
  }

  receive(message: unknown): void {
    this.handlers.onMessage(typeof message === "string" ? message : JSON.stringify(message));
  }

  drop(code: number): void {
    this.open = false;
    this.handlers.onError();
    this.handlers.onClose(code);
  }
}

function setup(readyTimeoutMs = 1000) {
  const sockets: FakeSocket[] = [];
  const controller = new CallController({
    url: "ws://test/ws/call",
    readyTimeoutMs,
    createSocket: (_url, handlers) => {
      const socket = new FakeSocket(handlers);
      sockets.push(socket);
      return socket;
    },
  });
  return { controller, sockets, latest: () => sockets[sockets.length - 1] };
}

/** A call that has connected and received `ready` and the greeting. */
function connectedCall() {
  const t = setup();
  t.controller.start();
  const socket = t.latest();
  socket.connect();
  socket.receive(fixtures.ready);
  socket.receive(fixtures.greeting_turn);
  return { ...t, socket };
}

const state = (controller: CallController) => controller.getState();

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("starting a call", () => {
  it("connects, receives ready and the greeting, then waits for the caller", () => {
    const { controller } = connectedCall();
    expect(state(controller).status).toBe("listening");
    expect(state(controller).limits).toEqual({ maxTextChars: 500, maxUtteranceSeconds: 30 });
    expect(state(controller).lines).toEqual([
      { id: 1, speaker: "bot", text: fixtures.greeting_turn.reply },
    ]);
    expect(state(controller).decision?.intent).toBe(fixtures.greeting_turn.trace.intent);
  });

  it("ignores a second Start while a call is running", () => {
    const { controller, sockets } = setup();
    controller.start();
    controller.start();
    expect(sockets).toHaveLength(1);
  });

  it("fails cleanly when the connection is refused before ready", () => {
    const { controller, latest } = setup();
    controller.start();
    const socket = latest();
    socket.drop(1006);
    expect(state(controller)).toMatchObject({ status: "failed", notice: MESSAGES.couldNotConnect });
    expect(socket.closeCalls).toBe(1);
    socket.drop(1006); // a late duplicate event changes nothing
    expect(socket.closeCalls).toBe(1);
  });

  it("reports 'busy' when the server is full (1013 arrives before ready)", () => {
    const { controller, latest } = setup();
    controller.start();
    latest().connect();
    latest().drop(1013);
    expect(state(controller)).toMatchObject({ status: "failed", notice: MESSAGES.busy });
  });

  it("gives up when ready never arrives", () => {
    const { controller, latest } = setup(1000);
    controller.start();
    latest().connect();
    vi.advanceTimersByTime(1000);
    expect(state(controller)).toMatchObject({ status: "failed", notice: MESSAGES.couldNotConnect });
    expect(latest().closeCalls).toBe(1);
  });

  it("fails if the server announces a different audio format", () => {
    const { controller, latest } = setup();
    controller.start();
    latest().receive({ ...fixtures.ready, sample_rate: 8000 });
    expect(state(controller).status).toBe("failed");
  });

  it("ignores a turn that arrives before ready", () => {
    const { controller, latest } = setup();
    controller.start();
    latest().receive(fixtures.greeting_turn);
    expect(state(controller)).toMatchObject({ status: "starting", lines: [] });
  });

  it("fails a socket that keeps sending invalid messages", () => {
    const { controller, socket } = connectedCall();
    socket.receive("{");
    socket.receive({ type: "surprise" });
    expect(state(controller).status).toBe("listening");
    socket.receive("[]");
    expect(state(controller)).toMatchObject({ status: "failed", notice: MESSAGES.generic });
  });
});

describe("talking by text", () => {
  it("sends one message, shows it, and waits for the reply", () => {
    const { controller, socket } = connectedCall();
    expect(controller.sendText("  what are your timings  ")).toBe(true);
    expect(socket.sent).toEqual([{ type: "text", text: "what are your timings" }]);
    expect(state(controller).status).toBe("thinking");
    expect(state(controller).lines.at(-1)).toMatchObject({ speaker: "caller", text: "what are your timings" });

    socket.receive(fixtures.text_turn);
    expect(state(controller).status).toBe("listening");
    expect(state(controller).lines.at(-1)).toMatchObject({ speaker: "bot", text: fixtures.text_turn.reply });
    expect(state(controller).decision).toMatchObject({ intent: "faq_hours" });
  });

  it("refuses a second message while one is in flight (no duplicates)", () => {
    const { controller, socket } = connectedCall();
    controller.sendText("first");
    expect(controller.sendText("second")).toBe(false);
    expect(socket.sent).toHaveLength(1);
  });

  it("does not send empty text", () => {
    const { controller, socket } = connectedCall();
    expect(controller.sendText("   ")).toBe(false);
    expect(socket.sent).toHaveLength(0);
  });

  it("does not send text over the server's limit", () => {
    const { controller, socket } = connectedCall();
    expect(controller.sendText("x".repeat(501))).toBe(false);
    expect(socket.sent).toHaveLength(0);
    expect(state(controller).notice).toBe(MESSAGES.tooLong);
  });

  it("does not send before the call is ready", () => {
    const { controller, latest } = setup();
    controller.start();
    latest().connect();
    expect(controller.sendText("hello")).toBe(false);
    expect(latest().sent).toHaveLength(0);
  });

  it("treats an error as the answer to the request in flight", () => {
    const { controller, socket } = connectedCall();
    controller.sendText("hello");
    socket.receive({ type: "error", code: "rate_limited", message: "server text" });
    expect(state(controller)).toMatchObject({ status: "listening", notice: MESSAGES.slowDown });
    expect(controller.sendText("hello again")).toBe(true);
  });

  it("never shows the server's own error text", () => {
    const { controller, socket } = connectedCall();
    socket.receive({ type: "error", code: "stt_unavailable", message: "internal detail" });
    expect(state(controller).notice).toBe(MESSAGES.sttUnavailable);
  });

  it("accepts a turn nobody asked for (the server's idle check)", () => {
    const { controller, socket } = connectedCall();
    socket.receive(fixtures.idle_turn);
    expect(state(controller).status).toBe("listening");
    expect(state(controller).lines.at(-1)).toMatchObject({ speaker: "bot", text: "Are you still there?" });
  });

  it("shows a transcript as the caller's line, but not an empty one", () => {
    const { controller, socket } = connectedCall();
    socket.receive(fixtures.audio_transcript);
    socket.receive({ type: "transcript", text: "" });
    const callerLines = state(controller).lines.filter((line) => line.speaker === "caller");
    expect(callerLines.map((line) => line.text)).toEqual(["what are your timings"]);
  });

  it("shows the restart notice and stays in the call", () => {
    const { controller, socket } = connectedCall();
    socket.receive(fixtures.closing);
    expect(state(controller)).toMatchObject({ status: "listening", notice: MESSAGES.restarting });
  });
});

describe("ending a call", () => {
  it("End sends one hangup and closes once, however often it is pressed", () => {
    const { controller, socket } = connectedCall();
    controller.end();
    controller.end();
    expect(socket.sent).toEqual([{ type: "hangup" }]);
    expect(socket.closeCalls).toBe(1);
    expect(state(controller)).toMatchObject({ status: "ended", notice: MESSAGES.callEnded });
  });

  it("End during start-up closes without a hangup and ignores a late ready", () => {
    const { controller, latest } = setup();
    controller.start();
    const socket = latest();
    controller.end();
    expect(socket.sent).toEqual([]);
    expect(socket.closeCalls).toBe(1);
    socket.connect();
    socket.receive(fixtures.ready);
    expect(state(controller)).toMatchObject({ status: "ended", limits: null });
  });

  it("ignores messages that arrive after the call ended", () => {
    const { controller, socket } = connectedCall();
    controller.end();
    const before = state(controller);
    socket.receive(fixtures.text_turn);
    socket.drop(1006);
    expect(state(controller)).toBe(before);
  });

  it("finishes when the server ends the call", () => {
    const { controller, socket } = connectedCall();
    socket.receive({ ...fixtures.text_turn, ended: true });
    expect(state(controller)).toMatchObject({ status: "ended", notice: MESSAGES.callEnded });
    expect(socket.closeCalls).toBe(1);
  });

  it.each([
    [1006, MESSAGES.disconnected],
    [1012, MESSAGES.restarting],
    [1001, MESSAGES.restarting],
    [1011, MESSAGES.serverError],
    [1008, MESSAGES.policy],
  ])("reports an unexpected close %i", (code, notice) => {
    const { controller, socket } = connectedCall();
    socket.drop(code);
    expect(state(controller)).toMatchObject({ status: "ended", notice });
  });

  it("cleans up even when closing the socket throws", () => {
    const { controller, socket } = connectedCall();
    socket.failOnClose = true;
    expect(() => controller.end()).not.toThrow();
    expect(state(controller).status).toBe("ended");
    expect(() => controller.end()).not.toThrow();
    expect(socket.closeCalls).toBe(1);
  });

  it("shutdown ends an active call and is harmless when idle", () => {
    const idle = setup();
    expect(() => idle.controller.shutdown()).not.toThrow();
    const { controller, socket } = connectedCall();
    controller.shutdown();
    controller.shutdown();
    expect(socket.sent).toEqual([{ type: "hangup" }]);
    expect(state(controller).status).toBe("ended");
  });
});

describe("a fresh call", () => {
  it("starts from nothing and ignores the previous call's socket", () => {
    const { controller, sockets, latest } = connectedCall();
    controller.sendText("what are your timings");
    sockets[0].receive(fixtures.text_turn);
    controller.end();

    controller.start();
    expect(sockets).toHaveLength(2);
    expect(state(controller)).toMatchObject({
      status: "starting",
      lines: [],
      decision: null,
      notice: null,
      limits: null,
    });

    sockets[0].receive(fixtures.text_turn); // the old socket is ignored
    expect(state(controller).lines).toEqual([]);

    latest().connect();
    latest().receive(fixtures.ready);
    latest().receive(fixtures.greeting_turn);
    expect(state(controller).status).toBe("listening");
    expect(state(controller).lines).toHaveLength(1);
  });

  it("can start again after a failed start", () => {
    const { controller, sockets, latest } = setup();
    controller.start();
    latest().drop(1006);
    controller.start();
    expect(sockets).toHaveLength(2);
    expect(state(controller).status).toBe("starting");
  });
});

// -- voice (steps 2 and 3) ------------------------------------------------------------------

class FakeSpeaker implements Speaker {
  spoken: string[] = [];
  cancelled = 0;
  private done: (() => void) | null = null;

  speak(text: string, onDone: () => void): void {
    this.spoken.push(text);
    this.done = onDone;
  }

  cancel(): void {
    this.cancelled += 1;
    this.done = null;
  }

  /** The browser finished saying the sentence. */
  finish(): void {
    const done = this.done;
    this.done = null;
    done?.();
  }
}

class FakeRecorder implements Recorder {
  stopped = 0;
  mutedHistory: boolean[] = [];
  maxSeconds = 0;

  constructor(readonly events: RecorderEvents) {}

  stop(): void {
    this.stopped += 1;
  }

  setMuted(muted: boolean): void {
    this.mutedHistory.push(muted);
  }

  setMaxSeconds(seconds: number): void {
    this.maxSeconds = seconds;
  }

  botSpeakingHistory: [speaking: boolean, guard: boolean][] = [];

  setBotSpeaking(speaking: boolean, guard: boolean): void {
    this.botSpeakingHistory.push([speaking, guard]);
  }

  get muted(): boolean | undefined {
    return this.mutedHistory.at(-1);
  }

  get botSpeaking(): boolean | undefined {
    return this.botSpeakingHistory.at(-1)?.[0];
  }
}

const flush = async () => {
  await Promise.resolve();
  await Promise.resolve();
};

function voiceSetup(mic: "grant" | "deny" | "later" = "grant", bargeIn?: boolean) {
  const sockets: FakeSocket[] = [];
  const speakers: FakeSpeaker[] = [];
  const recorders: FakeRecorder[] = [];
  let grantLater: () => void = () => {};
  const controller = new CallController({
    url: "ws://test/ws/call",
    readyTimeoutMs: 1000,
    bargeIn,
    createSocket: (_url, handlers) => {
      const socket = new FakeSocket(handlers);
      sockets.push(socket);
      return socket;
    },
    createSpeaker: () => {
      const speaker = new FakeSpeaker();
      speakers.push(speaker);
      return speaker;
    },
    createRecorder: (events) => {
      const recorder = new FakeRecorder(events);
      recorders.push(recorder);
      if (mic === "deny") return Promise.reject(Object.assign(new Error("no"), { name: "NotAllowedError" }));
      if (mic === "later") return new Promise((resolve) => (grantLater = () => resolve(recorder)));
      return Promise.resolve(recorder);
    },
  });
  return { controller, sockets, speakers, recorders, grantLater: () => grantLater() };
}

/** Mic granted, connected, greeting received (and being spoken). */
async function voiceCall(ready: unknown = fixtures.ready, bargeIn?: boolean) {
  const t = voiceSetup("grant", bargeIn);
  t.controller.start();
  await flush();
  const socket = t.sockets[0];
  socket.connect();
  socket.receive(ready);
  socket.receive(fixtures.greeting_turn);
  return { ...t, socket, speaker: t.speakers[0], recorder: t.recorders[0] };
}

describe("the bot's voice", () => {
  it("speaks each reply while listening strictly (so the caller can interrupt), then listens", async () => {
    const { controller, speaker, recorder } = await voiceCall();
    expect(state(controller).status).toBe("speaking");
    expect(speaker.spoken).toEqual([fixtures.greeting_turn.reply]);
    expect(recorder.muted).toBe(false);
    expect(recorder.botSpeaking).toBe(true);
    speaker.finish();
    expect(state(controller).status).toBe("listening");
    expect(recorder.botSpeaking).toBe(false);
    expect(recorder.botSpeakingHistory.at(-1)).toEqual([false, true]); // guard: its voice dies away
  });

  it("without interrupting, the microphone is muted while the bot speaks", async () => {
    const { controller, speaker, recorder } = await voiceCall(fixtures.ready, false);
    expect(recorder.muted).toBe(true);
    expect(recorder.botSpeaking).toBeUndefined();
    speaker.finish();
    expect(state(controller).status).toBe("listening");
    expect(recorder.muted).toBe(false);
  });

  it("typing while the bot speaks stops the voice", async () => {
    const { controller, speaker, socket } = await voiceCall();
    expect(controller.sendText("what are your timings")).toBe(true);
    expect(speaker.cancelled).toBe(1);
    expect(socket.sent).toEqual([{ type: "text", text: "what are your timings" }]);
    expect(state(controller).status).toBe("thinking");
  });

  it("still says goodbye when the server ends the call", async () => {
    const { speaker, socket, recorder, controller } = await voiceCall();
    speaker.finish();
    socket.receive({ ...fixtures.text_turn, ended: true });
    expect(speaker.spoken.at(-1)).toBe(fixtures.text_turn.reply);
    expect(speaker.cancelled).toBe(0); // the last sentence is not cut off
    expect(recorder.stopped).toBe(1);
    expect(state(controller)).toMatchObject({ status: "ended", mic: "off" });
  });
});

describe("the microphone", () => {
  it("follows the server's recording limit (minus a safety margin)", async () => {
    const { recorder } = await voiceCall();
    expect(recorder.maxSeconds).toBe(25); // min(25, 30 - 2)
    const short = await voiceCall({ ...fixtures.ready, limits: { ...fixtures.ready.limits, max_utterance_seconds: 20.0 } });
    expect(short.recorder.maxSeconds).toBe(18);
  });

  it("sends a finished utterance as one binary message", async () => {
    const { controller, speaker, recorder, socket } = await voiceCall();
    speaker.finish();
    recorder.events.onSpeechStart();
    expect(state(controller).status).toBe("hearing");
    recorder.events.onUtterance(new ArrayBuffer(32000));
    expect(socket.sent).toEqual([{ audioBytes: 32000 }]);
    expect(state(controller).status).toBe("thinking");
  });

  it("goes back to listening when speech was too short to send", async () => {
    const { controller, speaker, recorder, socket } = await voiceCall();
    speaker.finish();
    recorder.events.onSpeechStart();
    recorder.events.onSpeechDiscarded();
    expect(state(controller).status).toBe("listening");
    expect(socket.sent).toEqual([]);
  });

  it("shows the transcript, then speaks the reply", async () => {
    const { controller, speaker, recorder, socket } = await voiceCall();
    speaker.finish();
    recorder.events.onUtterance(new ArrayBuffer(32000));
    socket.receive(fixtures.audio_transcript);
    socket.receive(fixtures.audio_turn);
    const lines = state(controller).lines.map((line) => `${line.speaker}: ${line.text}`);
    expect(lines.slice(-2)).toEqual([
      "caller: what are your timings",
      `bot: ${fixtures.audio_turn.reply}`,
    ]);
    expect(state(controller).status).toBe("speaking");
  });

  it("drops what it hears while the bot speaks", async () => {
    const { recorder, socket } = await voiceCall();
    recorder.events.onUtterance(new ArrayBuffer(32000)); // still speaking the greeting
    expect(socket.sent).toEqual([]);
  });

  it("queues one utterance while waiting; the newest wins; sent after the reply is spoken", async () => {
    const { controller, speaker, recorder, socket } = await voiceCall();
    speaker.finish();
    recorder.events.onUtterance(new ArrayBuffer(1000));
    recorder.events.onUtterance(new ArrayBuffer(2000)); // queued
    recorder.events.onUtterance(new ArrayBuffer(3000)); // replaces the queued one
    expect(socket.sent).toEqual([{ audioBytes: 1000 }]);
    socket.receive(fixtures.audio_turn);
    expect(socket.sent).toHaveLength(1); // not while the bot is speaking
    speaker.finish();
    expect(socket.sent).toEqual([{ audioBytes: 1000 }, { audioBytes: 3000 }]);
    expect(state(controller).status).toBe("thinking");
  });

  it("an error answers the request and lets the queued utterance go", async () => {
    const { speaker, recorder, socket } = await voiceCall();
    speaker.finish();
    recorder.events.onUtterance(new ArrayBuffer(1000));
    recorder.events.onUtterance(new ArrayBuffer(2000));
    socket.receive({ type: "error", code: "stt_busy", message: "x" });
    expect(socket.sent).toEqual([{ audioBytes: 1000 }, { audioBytes: 2000 }]);
  });

  it("never sends a queued utterance after the call ends", async () => {
    const { controller, speaker, recorder, socket } = await voiceCall();
    speaker.finish();
    recorder.events.onUtterance(new ArrayBuffer(1000));
    recorder.events.onUtterance(new ArrayBuffer(2000));
    controller.end();
    expect(socket.sent).toEqual([{ audioBytes: 1000 }, { type: "hangup" }]);
  });

  it("End stops the microphone and the voice exactly once", async () => {
    const { controller, speaker, recorder } = await voiceCall();
    controller.end();
    controller.end();
    expect(recorder.stopped).toBe(1);
    expect(speaker.cancelled).toBe(1);
    expect(state(controller)).toMatchObject({ status: "ended", mic: "off" });
  });

  it("speech recognition unavailable: releases the mic and switches to typing", async () => {
    const { controller, speaker, recorder, socket } = await voiceCall();
    speaker.finish();
    recorder.events.onUtterance(new ArrayBuffer(1000));
    socket.receive(fixtures.error_stt_unavailable);
    expect(recorder.stopped).toBe(1);
    expect(state(controller)).toMatchObject({ status: "listening", mic: "unavailable" });
    expect(controller.sendText("what are your timings")).toBe(true);
  });

  it("a blocked microphone still allows a typed call", async () => {
    const { controller, sockets } = voiceSetup("deny");
    controller.start();
    await flush();
    expect(state(controller)).toMatchObject({ mic: "blocked", notice: MESSAGES.micBlocked });
    const socket = sockets[0];
    socket.connect();
    socket.receive(fixtures.ready);
    socket.receive(fixtures.greeting_turn);
    expect(controller.sendText("what are your timings")).toBe(true);
  });

  it("a microphone granted after the call ended is switched off at once", async () => {
    const { controller, recorders, grantLater } = voiceSetup("later");
    controller.start();
    controller.end();
    grantLater();
    await flush();
    expect(recorders[0].stopped).toBe(1);
    expect(state(controller)).toMatchObject({ status: "ended", mic: "off" });
  });
});
