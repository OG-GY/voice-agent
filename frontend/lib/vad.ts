// Energy-based voice activity detection, one 20 ms frame at a time.
//
// Speech = louder than max(noise floor x 3, an absolute minimum). The noise floor starts at a
// safe default (the caller may talk straight away, so there is no calibration window) and
// only adapts on frames that are not speech: down quickly, up slowly.
// Known limit: steady loud noise (TV, music) can look like speech; the text box is the fallback.

export interface VadConfig {
  startFrames: number; // loud frames in a row to start (3 = 60 ms)
  endFrames: number; // quiet frames in a row to end (40 = 0.8 s)
  ratio: number;
  absoluteMin: number;
  initialFloor: number;
  minFloor: number;
  maxFloor: number;
  floorFall: number; // how fast the floor follows quieter frames
  floorRise: number; // how fast it follows louder (non-speech) frames
  // While the bot is speaking (so we can tell an interruption from its own echo):
  strictRatio: number; // the threshold is multiplied by this
  strictStartFrames: number; // loud frames in a row needed to start (12 = 240 ms)
}

export const DEFAULT_VAD: VadConfig = {
  startFrames: 3,
  endFrames: 40,
  ratio: 3,
  absoluteMin: 0.01,
  initialFloor: 0.005,
  minFloor: 0.0005,
  maxFloor: 0.05,
  floorFall: 0.2,
  floorRise: 0.01,
  strictRatio: 2.5,
  strictStartFrames: 12,
};

export type VadEvent = "start" | "end" | null;

export function rms(frame: Float32Array): number {
  let sum = 0;
  for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
  return frame.length ? Math.sqrt(sum / frame.length) : 0;
}

export class Vad {
  private readonly config: VadConfig;
  private floor: number;
  private speaking = false;
  private loudRun = 0;
  private quietRun = 0;
  private speechFrames = 0;
  private strict = false;
  /** Loud frames in the utterance that just ended. */
  lastSpeechFrames = 0;

  constructor(config: Partial<VadConfig> = {}) {
    this.config = { ...DEFAULT_VAD, ...config };
    this.floor = this.config.initialFloor;
  }

  get isSpeaking(): boolean {
    return this.speaking;
  }

  get threshold(): number {
    const base = Math.max(this.floor * this.config.ratio, this.config.absoluteMin);
    return this.strict ? base * this.config.strictRatio : base;
  }

  /** Stricter detection while the bot is speaking. */
  setStrict(strict: boolean): void {
    this.strict = strict;
  }

  get noiseFloor(): number {
    return this.floor;
  }

  process(frame: Float32Array): VadEvent {
    const level = rms(frame);
    const loud = level > this.threshold;
    const c = this.config;

    if (!this.speaking) {
      if (loud) {
        this.loudRun += 1;
        if (this.loudRun >= (this.strict ? c.strictStartFrames : c.startFrames)) {
          this.speaking = true;
          this.speechFrames = this.loudRun;
          this.quietRun = 0;
          this.loudRun = 0;
          return "start";
        }
        return null;
      }
      this.loudRun = 0;
      if (!this.strict) this.adapt(level); // the bot's voice must not teach us a "noise floor"
      return null;
    }

    if (loud) {
      this.speechFrames += 1;
      this.quietRun = 0;
      return null;
    }
    this.quietRun += 1;
    if (this.quietRun >= c.endFrames) {
      this.lastSpeechFrames = this.speechFrames;
      this.speaking = false;
      this.quietRun = 0;
      this.speechFrames = 0;
      return "end";
    }
    return null;
  }

  /** Forget the current utterance (the learned noise floor is kept). */
  reset(): void {
    this.speaking = false;
    this.loudRun = 0;
    this.quietRun = 0;
    this.speechFrames = 0;
  }

  private adapt(level: number): void {
    const c = this.config;
    const rate = level < this.floor ? c.floorFall : c.floorRise;
    this.floor = Math.min(c.maxFloor, Math.max(c.minFloor, this.floor + (level - this.floor) * rate));
  }
}
