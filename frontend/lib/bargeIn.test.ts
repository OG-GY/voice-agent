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
import { isSuspectedEcho } from "./echo";
import { Vad } from "./vad";
import { FRAME_SAMPLES } from "./frames";
import { UtterancePipeline } from "./utterance";

// -- fakes (the controller never touches a real browser) ------------------------------------

class FakeSocket implements CallSocket {
  sent: unknown[] = [];
  open = true;
  constructor(readonly handlers: SocketHandlers) {}
  send(data: string | ArrayBuffer): void {
    this.sent.push(typeof data === "string" ? JSON.parse(data) : { audioBytes: data.byteLength });
  }
  close(): void {
    this.open = false;
  }
  isOpen(): boolean {
    return this.open;
  }
  receive(message: unknown): void {
    this.handlers.onMessage(JSON.stringify(message));
  }
}

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
  finish(): void {
    const done = this.done;
    this.done = null;
    done?.();
  }
}

class FakeRecorder implements Recorder {
  muted = true;
  botSpeaking = false;
  constructor(readonly events: RecorderEvents) {}
  stop(): void {}
  setMuted(muted: boolean): void {
    this.muted = muted;
  }
  setBotSpeaking(speaking: boolean): void {
    this.botSpeaking = speaking;
  }
  setMaxSeconds(): void {}
}

const flush = async () => {
  await Promise.resolve();
  await Promise.resolve();
};

const REPLY = fixtures.text_turn.reply; // what the bot says in these tests
const turnWith = (reply: string) => ({ ...fixtures.text_turn, reply });

function setup(bargeIn?: boolean) {
  const sockets: FakeSocket[] = [];
  const speakers: FakeSpeaker[] = [];
  const recorders: FakeRecorder[] = [];
  const controller = new CallController({
    url: "ws://test/ws/call",
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
      return Promise.resolve(recorder);
    },
  });
  return { controller, sockets, speakers, recorders };
}

/** A connected call whose greeting has been spoken and listened to: the bot then speaks REPLY. */
async function callWhereBotSpeaks(bargeIn?: boolean) {
  const t = setup(bargeIn);
  t.controller.start();
  await flush();
  const socket = t.sockets[0];
  const speaker = t.speakers[0];
  const recorder = t.recorders[0];
  socket.receive(fixtures.ready);
  socket.receive(fixtures.greeting_turn);
  speaker.finish();
  const askBotToSpeak = () => {
    // the caller says something, the server answers, the bot starts speaking REPLY
    recorder.events.onUtterance(new ArrayBuffer(32000));
    socket.receive(fixtures.audio_transcript);
    socket.receive(turnWith(REPLY));
  };
  return { ...t, socket, speaker, recorder, askBotToSpeak, state: () => t.controller.getState() };
}

/** The caller talks over the bot, and the server heard `heard` (undefined = no transcript). */
function interruptWith(
  c: Awaited<ReturnType<typeof callWhereBotSpeaks>>,
  heard: string | undefined,
  speech: "sentence" | "burst" = "sentence",
) {
  c.recorder.events.onSpeechStart();
  if (speech === "burst") {
    c.recorder.events.onSpeechDiscarded();
    return;
  }
  c.recorder.events.onUtterance(new ArrayBuffer(48000));
  if (heard !== undefined) c.socket.receive({ type: "transcript", text: heard });
  c.socket.receive(turnWith(REPLY)); // the bot answers, and starts speaking again
}

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

// -- the call flow --------------------------------------------------------------------------

describe("interrupting the bot", () => {
  it("stops the bot, tells the server once, and listens to the caller", async () => {
    const c = await callWhereBotSpeaks();
    c.askBotToSpeak();
    expect(c.state().status).toBe("speaking");
    expect(c.recorder.muted).toBe(false);
    expect(c.recorder.botSpeaking).toBe(true); // listening strictly

    c.recorder.events.onSpeechStart();
    expect(c.speaker.cancelled).toBe(1);
    expect(c.socket.sent.filter((m) => (m as { type?: string }).type === "barge_in")).toHaveLength(1);
    expect(c.state().status).toBe("hearing");
    expect(c.recorder.botSpeaking).toBe(false);
  });

  it("records the interruption as a normal turn and gets an answer", async () => {
    const c = await callWhereBotSpeaks();
    c.askBotToSpeak();
    interruptWith(c, "actually I would like a window table");
    const lines = c.state().lines.map((l) => `${l.speaker}: ${l.text}`);
    expect(lines).toContain("caller: actually I would like a window table");
    expect(c.state().status).toBe("speaking");
    expect(c.socket.sent.filter((m) => "audioBytes" in (m as object))).toHaveLength(2); // the first question, then the interruption
  });

  it("does not interrupt when the caller was only listening (nothing to cut)", async () => {
    const c = await callWhereBotSpeaks();
    c.recorder.events.onSpeechStart(); // the bot isn't speaking: this is a normal turn
    expect(c.speaker.cancelled).toBe(0);
    expect(c.socket.sent.some((m) => (m as { type?: string }).type === "barge_in")).toBe(false);
    expect(c.state().status).toBe("hearing");
  });

  it("is off when disabled: the microphone is muted instead", async () => {
    const c = await callWhereBotSpeaks(false);
    c.askBotToSpeak();
    expect(c.recorder.muted).toBe(true);
    c.recorder.events.onSpeechStart();
    expect(c.speaker.cancelled).toBe(0);
    expect(c.state().status).toBe("speaking");
  });

  it("ends cleanly if the call ends in the middle of an interruption", async () => {
    const c = await callWhereBotSpeaks();
    c.askBotToSpeak();
    c.recorder.events.onSpeechStart();
    c.controller.end();
    expect(c.state().status).toBe("ended");
    expect(() => c.controller.end()).not.toThrow();
  });
});

// -- the echo fallback ----------------------------------------------------------------------

describe("when the bot hears itself", () => {
  const echoOfReply = REPLY.split(" ").slice(0, 8).join(" ");

  it("two suspected echoes in a row switch this call to no-interrupting", async () => {
    const c = await callWhereBotSpeaks();
    c.askBotToSpeak();
    interruptWith(c, echoOfReply); // strike 1: it heard the bot's own words
    expect(c.state().notice).not.toBe(MESSAGES.echoOff);
    interruptWith(c, ""); // strike 2: nothing usable
    expect(c.state().notice).toBe(MESSAGES.echoOff);
    // from now on the microphone is muted while the bot speaks
    expect(c.state().status).toBe("speaking");
    expect(c.recorder.muted).toBe(true);
    const cancelled = c.speaker.cancelled;
    c.recorder.events.onSpeechStart();
    expect(c.speaker.cancelled).toBe(cancelled);
  });

  it("a reply without any transcript counts as hearing nothing", async () => {
    const c = await callWhereBotSpeaks();
    c.askBotToSpeak();
    interruptWith(c, undefined);
    interruptWith(c, undefined);
    expect(c.state().notice).toBe(MESSAGES.echoOff);
  });

  it("a burst too short to send counts too", async () => {
    const c = await callWhereBotSpeaks();
    c.askBotToSpeak();
    c.recorder.events.onSpeechStart();
    c.recorder.events.onSpeechDiscarded();
    expect(c.state().notice).not.toBe(MESSAGES.echoOff);
    c.askBotToSpeak();
    c.recorder.events.onSpeechStart();
    c.recorder.events.onSpeechDiscarded();
    expect(c.state().notice).toBe(MESSAGES.echoOff);
  });

  it("does NOT switch off for a real person, even one the server understood badly", async () => {
    const c = await callWhereBotSpeaks();
    c.askBotToSpeak();
    interruptWith(c, "a table for four on saturday please");
    interruptWith(c, "no wait make it five"); // not an echo, whatever the brain made of it
    interruptWith(c, "sorry what did you say about the window");
    expect(c.state().notice).not.toBe(MESSAGES.echoOff);
    expect(c.recorder.muted).toBe(false);
  });

  it("a real interruption in between resets the count", async () => {
    const c = await callWhereBotSpeaks();
    c.askBotToSpeak();
    interruptWith(c, echoOfReply); // strike 1
    interruptWith(c, "yes please book the window table"); // a real person: reset
    interruptWith(c, echoOfReply); // strike 1 again, not 2
    expect(c.state().notice).not.toBe(MESSAGES.echoOff);
    expect(c.recorder.muted).toBe(false);
  });

  it("an error reply is no evidence either way", async () => {
    const c = await callWhereBotSpeaks();
    c.askBotToSpeak();
    for (let i = 0; i < 3; i++) {
      c.recorder.events.onSpeechStart();
      c.recorder.events.onUtterance(new ArrayBuffer(48000));
      c.socket.receive({ type: "error", code: "stt_busy", message: "x" });
      c.askBotToSpeak();
    }
    expect(c.state().notice).not.toBe(MESSAGES.echoOff);
  });

  it("the next call allows interrupting again", async () => {
    const c = await callWhereBotSpeaks();
    c.askBotToSpeak();
    interruptWith(c, "");
    interruptWith(c, "");
    expect(c.state().notice).toBe(MESSAGES.echoOff);
    c.controller.end();

    c.controller.start();
    await flush();
    const socket = c.sockets[1];
    const speaker = c.speakers[1];
    const recorder = c.recorders[1];
    socket.receive(fixtures.ready);
    socket.receive(fixtures.greeting_turn); // the bot speaks the greeting
    expect(c.state().notice).toBeNull();
    expect(recorder.muted).toBe(false);
    recorder.events.onSpeechStart(); // interrupting works in the fresh call
    expect(speaker.cancelled).toBe(1);
  });
});

// -- echo detection -------------------------------------------------------------------------

describe("suspected echo", () => {
  const reply =
    "Certainly, I'll book a table for you. Would you like a private family table, a window-side table, or shall I book a general one?";

  it("nothing usable heard is a suspected echo", () => {
    expect(isSuspectedEcho("", reply)).toBe(true);
    expect(isSuspectedEcho("   ", reply)).toBe(true);
  });

  it("a stretch of the bot's own sentence is", () => {
    expect(isSuspectedEcho("would you like a private family table", reply)).toBe(true);
    expect(isSuspectedEcho("Would you like a private family table, a window side table?", reply)).toBe(true);
  });

  it("a caller answering with words from the question is not", () => {
    expect(isSuspectedEcho("a window table please", reply)).toBe(false);
    expect(isSuspectedEcho("I'd like the private family one", reply)).toBe(false);
    expect(isSuspectedEcho("yes the window table", reply)).toBe(false);
  });

  it("very short speech is treated as a real person", () => {
    expect(isSuspectedEcho("window", reply)).toBe(false);
    expect(isSuspectedEcho("yes please", reply)).toBe(false);
  });

  it("ignores case and punctuation", () => {
    expect(isSuspectedEcho("WOULD YOU LIKE... a private, family table!", reply)).toBe(true);
  });
});

// -- strict listening while the bot speaks --------------------------------------------------

describe("listening while the bot speaks", () => {
  const frame = (amplitude: number) => {
    const out = new Float32Array(FRAME_SAMPLES);
    for (let i = 0; i < out.length; i++) out[i] = amplitude * Math.sin((2 * Math.PI * 300 * i) / 16000);
    return out;
  };

  it("needs louder and longer speech than normal", () => {
    const quietVoice = frame(0.025); // above the normal threshold, below the strict one
    const normal = new Vad();
    expect([normal.process(quietVoice), normal.process(quietVoice), normal.process(quietVoice)]).toContain("start");

    const strict = new Vad();
    strict.setStrict(true);
    for (let i = 0; i < 30; i++) expect(strict.process(quietVoice)).toBeNull();

    const loud = frame(0.3);
    const results = Array.from({ length: 12 }, () => strict.process(loud));
    expect(results.indexOf("start")).toBe(11); // only after 12 frames (240 ms)
  });

  it("does not learn the bot's voice as background noise", () => {
    const vad = new Vad();
    vad.setStrict(true);
    for (let i = 0; i < 300; i++) vad.process(frame(0.012));
    expect(vad.noiseFloor).toBeCloseTo(0.005, 3); // unchanged
  });

  describe("in the pipeline", () => {
    const RATE = 16_000;
    const speech = (seconds: number) => {
      const out = new Float32Array(Math.round(RATE * seconds));
      for (let i = 0; i < out.length; i++) out[i] = 0.3 * Math.sin((2 * Math.PI * 300 * i) / RATE);
      return out;
    };
    const quiet = (seconds: number) => new Float32Array(Math.round(RATE * seconds));

    function pipeline() {
      const events = { starts: 0, utterances: [] as Float32Array[] };
      const p = new UtterancePipeline(RATE, {
        onSpeechStart: () => (events.starts += 1),
        onDiscard: () => {},
        onUtterance: (s) => events.utterances.push(s),
      });
      return { p, events };
    }

    it("still hears an interruption while the bot speaks, and keeps its first words", () => {
      const { p, events } = pipeline();
      p.setBotSpeaking(true, false);
      p.push(quiet(0.5));
      p.push(speech(1.5));
      expect(events.starts).toBe(1);
      p.push(quiet(1));
      expect(events.utterances).toHaveLength(1);
      expect(events.utterances[0].length / RATE).toBeGreaterThan(1.5); // includes the lead-in
    });

    it("ignores the bot's voice dying away right after it stops, but never cuts a speaker off", () => {
      const a = pipeline();
      a.p.setBotSpeaking(true, false);
      a.p.setBotSpeaking(false, true); // the bot finished: 0.3 s guard
      a.p.push(speech(0.2)); // the bot's tail
      a.p.push(quiet(1));
      expect(a.events.starts).toBe(0);

      const b = pipeline();
      b.p.setBotSpeaking(true, false);
      b.p.push(speech(0.6)); // the caller interrupts...
      expect(b.events.starts).toBe(1);
      b.p.setBotSpeaking(false, false); // ...and the bot is stopped: no guard
      b.p.push(speech(0.6));
      b.p.push(quiet(1));
      expect(b.events.utterances).toHaveLength(1);
      expect(b.events.utterances[0].length / RATE).toBeGreaterThan(1.2); // nothing swallowed
    });
  });
});
