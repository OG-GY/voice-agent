import { describe, expect, it } from "vitest";

import { FrameSplitter, FRAME_SAMPLES } from "./frames";
import { concatFrames, toPcm16 } from "./pcm";
import { Resampler, TARGET_RATE } from "./resampler";
import { MIN_SPEECH_FRAMES, UtterancePipeline } from "./utterance";
import { rms, Vad } from "./vad";

function tone(rate: number, hz: number, seconds: number, amplitude = 1): Float32Array {
  const out = new Float32Array(Math.round(rate * seconds));
  for (let i = 0; i < out.length; i++) out[i] = amplitude * Math.sin((2 * Math.PI * hz * i) / rate);
  return out;
}

const silence = (rate: number, seconds: number) => new Float32Array(Math.round(rate * seconds));

function zeroCrossings(samples: Float32Array): number {
  let count = 0;
  for (let i = 1; i < samples.length; i++) if (samples[i - 1] < 0 !== samples[i] < 0) count += 1;
  return count;
}

/** The middle of a signal, away from the start-up and end edges. */
const middle = (samples: Float32Array) => samples.subarray(samples.length / 4, (samples.length * 3) / 4);

describe("resampler", () => {
  it.each([48_000, 44_100])("produces the right number of samples from %i Hz", (rate) => {
    const resampler = new Resampler(rate);
    const input = silence(rate, 1);
    const out = resampler.process(input);
    const expected = (input.length - resampler.halfWidth) * (TARGET_RATE / rate);
    expect(Math.abs(out.length - expected)).toBeLessThanOrEqual(1);
  });

  it.each([48_000, 44_100])("keeps a 1 kHz tone's pitch and loudness from %i Hz", (rate) => {
    const out = middle(new Resampler(rate).process(tone(rate, 1000, 1)));
    const seconds = out.length / TARGET_RATE;
    expect(zeroCrossings(out) / seconds).toBeCloseTo(2000, -1); // 2 crossings per cycle
    expect(rms(out) / Math.SQRT1_2).toBeGreaterThan(0.95);
    expect(rms(out) / Math.SQRT1_2).toBeLessThan(1.05);
  });

  it.each([48_000, 44_100])("removes a 10 kHz tone (above 8 kHz) from %i Hz instead of aliasing it", (rate) => {
    const out = middle(new Resampler(rate).process(tone(rate, 10_000, 1)));
    const db = 20 * Math.log10(rms(out) / Math.SQRT1_2);
    expect(db).toBeLessThan(-30);
  });

  it.each([48_000, 44_100])("gives identical output in chunks or all at once (%i Hz)", (rate) => {
    const input = tone(rate, 440, 0.5, 0.5);
    const whole = new Resampler(rate).process(input);
    const chunked = new Resampler(rate);
    const pieces: Float32Array[] = [];
    for (let at = 0, size = 1; at < input.length; at += size, size = (size * 7 + 3) % 977 || 1) {
      pieces.push(chunked.process(input.subarray(at, Math.min(input.length, at + size))));
    }
    expect(Array.from(concatFrames(pieces))).toEqual(Array.from(whole));
  });

  it("rejects impossible rates", () => {
    expect(() => new Resampler(0)).toThrow(RangeError);
  });
});

describe("frame splitter", () => {
  it("cuts exact 320-sample frames and carries the rest over", () => {
    const splitter = new FrameSplitter();
    expect(splitter.push(new Float32Array(300))).toHaveLength(0);
    const frames = splitter.push(new Float32Array(400));
    expect(frames).toHaveLength(2);
    expect(frames.every((frame) => frame.length === FRAME_SAMPLES)).toBe(true);
  });
});

describe("voice activity detection", () => {
  const quiet = new Float32Array(FRAME_SAMPLES);
  const loud = tone(TARGET_RATE, 300, FRAME_SAMPLES / TARGET_RATE, 0.3);

  it("stays silent on silence", () => {
    const vad = new Vad();
    for (let i = 0; i < 200; i++) expect(vad.process(quiet)).toBeNull();
  });

  it("starts after 3 loud frames and ends after 40 quiet ones", () => {
    const vad = new Vad();
    expect([vad.process(loud), vad.process(loud), vad.process(loud)]).toEqual([null, null, "start"]);
    for (let i = 0; i < 20; i++) vad.process(loud);
    for (let i = 0; i < 39; i++) expect(vad.process(quiet)).toBeNull();
    expect(vad.process(quiet)).toBe("end");
    expect(vad.lastSpeechFrames).toBe(23);
  });

  it("ignores a single click", () => {
    const vad = new Vad();
    expect([vad.process(loud), vad.process(quiet), vad.process(loud)]).toEqual([null, null, null]);
  });

  it("learns a quiet room's noise floor without treating it as speech", () => {
    const vad = new Vad();
    const hum = tone(TARGET_RATE, 120, FRAME_SAMPLES / TARGET_RATE, 0.004);
    for (let i = 0; i < 300; i++) expect(vad.process(hum)).toBeNull();
    expect(vad.noiseFloor).toBeGreaterThan(0.002);
    expect([vad.process(loud), vad.process(loud), vad.process(loud)]).toContain("start");
  });
});

describe("pcm16", () => {
  it("writes little-endian 16-bit samples and clips out-of-range values", () => {
    const view = new DataView(toPcm16(Float32Array.from([0, 1, -1, 2, -2, 0.5])));
    expect(view.byteLength).toBe(12);
    expect([0, 1, 2, 3, 4, 5].map((i) => view.getInt16(i * 2, true))).toEqual([
      0, 32767, -32768, 32767, -32768, 16384,
    ]);
  });
});

describe("utterance pipeline", () => {
  const RATE = 48_000;

  function run(chunks: Float32Array[], configure?: (p: UtterancePipeline) => void) {
    const events = { starts: 0, discards: 0, utterances: [] as Float32Array[] };
    const pipeline = new UtterancePipeline(RATE, {
      onSpeechStart: () => (events.starts += 1),
      onDiscard: () => (events.discards += 1),
      onUtterance: (samples) => events.utterances.push(samples),
    });
    configure?.(pipeline);
    for (const chunk of chunks) pipeline.push(chunk);
    return { events, pipeline };
  }

  const speech = (seconds: number) => tone(RATE, 300, seconds, 0.3);

  it("sends nothing for silence", () => {
    const { events } = run([silence(RATE, 3)]);
    expect(events).toEqual({ starts: 0, discards: 0, utterances: [] });
  });

  it("assembles one utterance, with pre-roll, after the caller stops", () => {
    const { events } = run([silence(RATE, 0.5), speech(1), silence(RATE, 1)]);
    expect(events.starts).toBe(1);
    expect(events.utterances).toHaveLength(1);
    const seconds = events.utterances[0].length / TARGET_RATE;
    expect(seconds).toBeGreaterThan(1 + 0.8); // speech + the 0.8 s of quiet that ended it
    expect(seconds).toBeLessThan(1 + 0.8 + 0.4); // + at most the 0.3 s pre-roll
  });

  it("does not send until the utterance is finished", () => {
    const { events } = run([speech(1), silence(RATE, 0.5)]); // not yet 0.8 s of quiet
    expect(events.starts).toBe(1);
    expect(events.utterances).toHaveLength(0);
  });

  it("drops speech shorter than the minimum", () => {
    expect(MIN_SPEECH_FRAMES).toBe(15);
    const { events } = run([speech(0.12), silence(RATE, 1)]);
    expect(events.starts).toBe(1);
    expect(events.discards).toBe(1);
    expect(events.utterances).toHaveLength(0);
  });

  it("splits a very long utterance at the cap", () => {
    const { events } = run([speech(2.5), silence(RATE, 1)], (p) => p.setMaxSeconds(1));
    expect(events.utterances.length).toBeGreaterThanOrEqual(2);
    for (const u of events.utterances.slice(0, -1)) expect(u.length / TARGET_RATE).toBeLessThanOrEqual(1.01);
  });

  it("hears nothing while muted, and ignores the first moment after unmuting", () => {
    const { events, pipeline } = run([], (p) => p.setMuted(true));
    pipeline.push(speech(1));
    pipeline.push(silence(RATE, 1));
    expect(events.starts).toBe(0);
    pipeline.setMuted(false);
    pipeline.push(speech(0.2)); // swallowed by the guard (bot's voice dying away)
    pipeline.push(silence(RATE, 1));
    expect(events.starts).toBe(0);
  });

  it("muting in the middle of speech drops that speech", () => {
    const { events, pipeline } = run([speech(0.5)]);
    expect(events.starts).toBe(1);
    pipeline.setMuted(true);
    expect(events.discards).toBe(1);
    pipeline.push(silence(RATE, 1));
    expect(events.utterances).toHaveLength(0);
  });

  it("gives the same utterances whatever the chunk size", () => {
    const audio = concatFrames([silence(RATE, 0.3), speech(0.8), silence(RATE, 1)]);
    const whole = run([audio]).events.utterances;
    const chunks: Float32Array[] = [];
    for (let at = 0; at < audio.length; at += 960) chunks.push(audio.subarray(at, at + 960));
    const chunked = run(chunks).events.utterances;
    expect(chunked.map((u) => Array.from(u))).toEqual(whole.map((u) => Array.from(u)));
  });
});
