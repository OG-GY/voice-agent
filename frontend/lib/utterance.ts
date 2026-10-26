// From raw microphone chunks to finished utterances:
//   chunks (device rate) -> resampler (16 kHz) -> 20 ms frames -> VAD -> assembly
//
// Frames are collected (with a 0.3 s pre-roll so the first syllable isn't cut) until the VAD
// says the caller stopped. Only then is the whole utterance handed over, exactly once.
// Nothing is ever sent frame by frame.

import { concatFrames } from "./pcm";
import { FRAMES_PER_SECOND, FrameSplitter } from "./frames";
import { Resampler } from "./resampler";
import { Vad, type VadConfig } from "./vad";

export const PRE_ROLL_FRAMES = 15; // 0.3 s kept from before speech started
export const MIN_SPEECH_FRAMES = 15; // 0.3 s of speech; shorter is dropped (server minimum is 0.2 s)
export const GUARD_FRAMES = 15; // 0.3 s ignored after unmuting (the bot's voice dying away)
export const DEFAULT_MAX_SECONDS = 25;

export interface PipelineEvents {
  onSpeechStart(): void;
  /** Speech started but was too short to send. */
  onDiscard(): void;
  /** A finished utterance: 16 kHz mono float samples. */
  onUtterance(samples: Float32Array): void;
}

export interface PipelineOptions {
  maxSeconds?: number;
  vad?: Partial<VadConfig>;
}

export class UtterancePipeline {
  private readonly resampler: Resampler;
  private readonly splitter = new FrameSplitter();
  private readonly vad: Vad;
  private preRoll: Float32Array[] = [];
  private collected: Float32Array[] | null = null;
  private muted = false;
  private botSpeaking = false;
  private guard = 0;
  private maxFrames: number;

  constructor(
    inputRate: number,
    private readonly events: PipelineEvents,
    options: PipelineOptions = {},
  ) {
    this.resampler = new Resampler(inputRate);
    this.vad = new Vad(options.vad);
    this.maxFrames = this.framesFor(options.maxSeconds ?? DEFAULT_MAX_SECONDS);
  }

  setMaxSeconds(seconds: number): void {
    this.maxFrames = this.framesFor(seconds);
  }

  /** While muted (the bot is speaking) frames are thrown away. */
  setMuted(muted: boolean): void {
    if (muted === this.muted) return;
    this.muted = muted;
    if (muted) this.dropCurrent();
    else this.guard = GUARD_FRAMES;
  }

  /**
   * The bot is speaking but the caller may interrupt: keep listening, but more strictly
   * (so the bot's own voice isn't mistaken for the caller). `guard` = ignore the first 0.3 s
   * after the bot stops, while its voice dies away; pass false when the caller interrupted.
   */
  setBotSpeaking(speaking: boolean, guard: boolean): void {
    if (speaking === this.botSpeaking) return;
    this.botSpeaking = speaking;
    this.vad.setStrict(speaking);
    if (!speaking && guard) this.guard = GUARD_FRAMES;
  }

  push(chunk: Float32Array): void {
    for (const frame of this.splitter.push(this.resampler.process(chunk))) this.onFrame(frame);
  }

  reset(): void {
    this.collected = null;
    this.preRoll = [];
    this.guard = 0;
    this.botSpeaking = false;
    this.vad.setStrict(false);
    this.vad.reset();
    this.splitter.reset();
  }

  private framesFor(seconds: number): number {
    return Math.max(1, Math.floor(seconds * FRAMES_PER_SECOND));
  }

  private dropCurrent(): void {
    const wasCollecting = this.collected !== null;
    this.collected = null;
    this.preRoll = [];
    this.vad.reset();
    if (wasCollecting) this.events.onDiscard();
  }

  private onFrame(frame: Float32Array): void {
    if (this.muted) return;
    // The guard never swallows an utterance that is already being collected.
    if (this.guard > 0 && this.collected === null) {
      this.guard -= 1;
      return;
    }
    const event = this.vad.process(frame);

    if (this.collected === null) {
      this.preRoll.push(frame);
      if (this.preRoll.length > PRE_ROLL_FRAMES) this.preRoll.shift();
      if (event === "start") {
        this.collected = this.preRoll;
        this.preRoll = [];
        this.events.onSpeechStart();
      }
      return;
    }

    this.collected.push(frame);
    if (event === "end") {
      this.finish(this.vad.lastSpeechFrames >= MIN_SPEECH_FRAMES);
    } else if (this.collected.length >= this.maxFrames) {
      this.vad.reset(); // the cap: send what we have; the VAD starts afresh
      this.finish(true);
    }
  }

  private finish(keep: boolean): void {
    const frames = this.collected ?? [];
    this.collected = null;
    if (keep) this.events.onUtterance(concatFrames(frames));
    else this.events.onDiscard();
  }
}
