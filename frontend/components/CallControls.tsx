import { isInCall, type CallStatus, type MicStatus } from "@/lib/callController";

const LABELS: Record<CallStatus, string> = {
  idle: "Idle",
  starting: "Connecting…",
  listening: "Listening: go ahead",
  hearing: "Hearing you…",
  thinking: "Thinking…",
  speaking: "Speaking…",
  ending: "Ending…",
  ended: "Ended",
  failed: "Failed",
};

const MIC_LABELS: Record<MicStatus, string> = {
  off: "off",
  requesting: "asking for permission…",
  on: "on",
  blocked: "blocked (type instead)",
  unavailable: "not available (type instead)",
};

interface Props {
  status: CallStatus;
  mic: MicStatus;
  onStart: () => void;
  onEnd: () => void;
}

export function CallControls({ status, mic, onStart, onEnd }: Props) {
  const inCall = isInCall(status);
  const typingOnly = mic === "blocked" || mic === "unavailable";
  const label = status === "listening" && typingOnly ? "Your turn: type below" : LABELS[status];
  return (
    <section className="call-controls" aria-label="Call controls">
      {inCall ? (
        <button type="button" className="button end" onClick={onEnd}>
          End call
        </button>
      ) : (
        <button type="button" className="button start" onClick={onStart} disabled={status === "ending"}>
          Start call
        </button>
      )}
      <div className="status-block">
        <p className={`status status-${status}`} aria-live="polite">
          Status: <strong>{label}</strong>
        </p>
        {inCall && <p className="mic">Microphone: {MIC_LABELS[mic]}</p>}
      </div>
    </section>
  );
}
