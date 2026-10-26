// Cut a stream of samples into fixed 20 ms frames (320 samples at 16 kHz),
// carrying the leftover samples over to the next call.

export const FRAME_SAMPLES = 320;
export const FRAMES_PER_SECOND = 50;

export class FrameSplitter {
  private pending: Float32Array;
  private filled = 0;

  constructor(private readonly size: number = FRAME_SAMPLES) {
    this.pending = new Float32Array(size);
  }

  push(samples: Float32Array): Float32Array[] {
    const frames: Float32Array[] = [];
    let read = 0;
    while (read < samples.length) {
      const take = Math.min(this.size - this.filled, samples.length - read);
      this.pending.set(samples.subarray(read, read + take), this.filled);
      this.filled += take;
      read += take;
      if (this.filled === this.size) {
        frames.push(this.pending);
        this.pending = new Float32Array(this.size);
        this.filled = 0;
      }
    }
    return frames;
  }

  reset(): void {
    this.pending = new Float32Array(this.size);
    this.filled = 0;
  }
}
