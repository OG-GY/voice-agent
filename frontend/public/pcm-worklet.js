// Runs on the audio thread. No logic here: mix to mono, batch into ~20 ms chunks at the
// device's own sample rate, and hand each chunk to the page (resampling happens there).

class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.size = Math.max(128, Math.round(sampleRate * 0.02));
    this.batch = new Float32Array(this.size);
    this.filled = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (input && input.length > 0) {
      const channels = input.length;
      const frames = input[0].length;
      for (let i = 0; i < frames; i++) {
        let sum = 0;
        for (let c = 0; c < channels; c++) sum += input[c][i];
        this.batch[this.filled++] = sum / channels;
        if (this.filled === this.size) {
          this.port.postMessage(this.batch, [this.batch.buffer]);
          this.batch = new Float32Array(this.size);
          this.filled = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor("pcm-capture", PcmCapture);
