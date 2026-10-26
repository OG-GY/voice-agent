// Streaming resampler to 16 kHz (any input rate: 44.1 kHz, 48 kHz, ...).
//
// Band-limited interpolation: every output sample is a weighted sum of nearby input samples,
// weighted by a Blackman-windowed sinc low-pass kernel (cutoff 0.45 x the output rate,
// 7.2 kHz at 16 kHz). That both interpolates at fractional positions and removes what
// would otherwise alias into the speech band.
//
// The state (unused input samples, next output position) carries over between calls, so
// feeding audio in chunks gives exactly the same output as feeding it all at once.

export const TARGET_RATE = 16_000;
const ZERO_CROSSINGS = 12; // kernel half-width, in zero crossings of the sinc
const CUTOFF = 0.45; // of the lower of the two sample rates
const TABLE_RESOLUTION = 256; // kernel samples per input sample (linear interpolation between)

function kernel(distance: number, cutoff: number, halfWidth: number): number {
  if (distance >= halfWidth) return 0;
  const u = distance / halfWidth;
  const window = 0.42 + 0.5 * Math.cos(Math.PI * u) + 0.08 * Math.cos(2 * Math.PI * u);
  const a = 2 * cutoff * distance;
  const sinc = a === 0 ? 1 : Math.sin(Math.PI * a) / (Math.PI * a);
  return 2 * cutoff * sinc * window;
}

export class Resampler {
  /** Input samples on each side of an output sample that contribute to it (also the latency). */
  readonly halfWidth: number;
  private readonly step: number;
  private readonly table: Float32Array;
  private buffer = new Float32Array(0); // input samples still needed
  private offset = 0; // absolute index of buffer[0]
  private position = 0; // absolute input position of the next output sample

  constructor(
    readonly inputRate: number,
    readonly outputRate: number = TARGET_RATE,
  ) {
    if (!(inputRate > 0) || !(outputRate > 0)) throw new RangeError("sample rates must be positive");
    this.step = inputRate / outputRate;
    const cutoff = (CUTOFF * Math.min(inputRate, outputRate)) / inputRate; // cycles per input sample
    this.halfWidth = ZERO_CROSSINGS / (2 * cutoff);
    const size = Math.ceil(this.halfWidth * TABLE_RESOLUTION) + 2;
    this.table = new Float32Array(size);
    for (let i = 0; i < size; i++) this.table[i] = kernel(i / TABLE_RESOLUTION, cutoff, this.halfWidth);
  }

  process(input: Float32Array): Float32Array {
    const data = new Float32Array(this.buffer.length + input.length);
    data.set(this.buffer);
    data.set(input, this.buffer.length);
    const end = this.offset + data.length; // absolute index just past the last sample

    const out: number[] = [];
    while (Math.floor(this.position + this.halfWidth) < end) {
      out.push(this.sampleAt(data, this.position));
      this.position += this.step;
    }

    // Keep only what future output samples can still reach.
    const keepFrom = Math.max(this.offset, Math.ceil(this.position - this.halfWidth));
    this.buffer = data.slice(keepFrom - this.offset);
    this.offset = keepFrom;
    return Float32Array.from(out);
  }

  private sampleAt(data: Float32Array, position: number): number {
    const last = Math.floor(position + this.halfWidth);
    let sum = 0;
    for (let i = Math.ceil(position - this.halfWidth); i <= last; i++) {
      const index = i - this.offset;
      if (index < 0) continue; // before the start of the stream: silence
      sum += data[index] * this.weight(position - i);
    }
    return sum;
  }

  private weight(distance: number): number {
    const x = Math.abs(distance) * TABLE_RESOLUTION;
    const i = Math.floor(x);
    if (i + 1 >= this.table.length) return 0;
    return this.table[i] + (this.table[i + 1] - this.table[i]) * (x - i);
  }
}
