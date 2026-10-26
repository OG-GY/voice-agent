// The real microphone behind the controller's recorder port (browser only; called from start()).
// mic -> MediaStreamSource -> pcm-worklet -> UtterancePipeline -> PCM16 -> onUtterance

import type { Recorder, RecorderEvents } from "./callController";
import { toPcm16 } from "./pcm";
import { UtterancePipeline } from "./utterance";

const WORKLET_URL = "/pcm-worklet.js";
const WORKLET_NAME = "pcm-capture";

class UnsupportedError extends Error {
  override name = "NotSupportedError";
}

export async function createMicRecorder(events: RecorderEvents): Promise<Recorder> {
  if (
    typeof navigator === "undefined" ||
    !navigator.mediaDevices?.getUserMedia ||
    typeof AudioContext === "undefined" ||
    typeof AudioWorkletNode === "undefined"
  ) {
    throw new UnsupportedError("this browser cannot record audio here");
  }

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
  });
  const context = new AudioContext();
  let pipeline: UtterancePipeline | null = null;
  let source: MediaStreamAudioSourceNode | null = null;
  let node: AudioWorkletNode | null = null;
  let sink: GainNode | null = null;
  let stopped = false;

  // Releases everything; safe to call more than once.
  const stop = (): void => {
    if (stopped) return;
    stopped = true;
    if (node) node.port.onmessage = null;
    for (const audioNode of [source, node, sink]) {
      try {
        audioNode?.disconnect();
      } catch {
        // already disconnected
      }
    }
    for (const track of stream.getTracks()) {
      try {
        track.stop(); // turns off the browser's microphone indicator
      } catch {
        // already stopped
      }
    }
    context.close().catch(() => {});
    pipeline?.reset();
    pipeline = null;
  };

  try {
    await context.audioWorklet.addModule(WORKLET_URL);
    pipeline = new UtterancePipeline(context.sampleRate, {
      onSpeechStart: () => events.onSpeechStart(),
      onDiscard: () => events.onSpeechDiscarded(),
      onUtterance: (samples) => events.onUtterance(toPcm16(samples)),
    });
    source = context.createMediaStreamSource(stream);
    node = new AudioWorkletNode(context, WORKLET_NAME);
    sink = context.createGain();
    sink.gain.value = 0; // keeps the worklet running without playing the mic back
    node.port.onmessage = (event: MessageEvent<Float32Array>) => pipeline?.push(event.data);
    source.connect(node);
    node.connect(sink);
    sink.connect(context.destination);
    if (context.state === "suspended") await context.resume();
  } catch (error) {
    stop();
    throw error;
  }

  return {
    stop,
    setMuted: (muted) => pipeline?.setMuted(muted),
    setBotSpeaking: (speaking, guard) => pipeline?.setBotSpeaking(speaking, guard),
    setMaxSeconds: (seconds) => pipeline?.setMaxSeconds(seconds),
  };
}
