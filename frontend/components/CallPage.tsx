"use client";

import { useCall } from "@/hooks/useCall";
import { canType, isInCall } from "@/lib/callController";

import { CallControls } from "./CallControls";
import { Conversation } from "./Conversation";
import { DecisionPanel } from "./DecisionPanel";
import { TextFallback } from "./TextFallback";

const DEFAULT_MAX_TEXT = 500;

export function CallPage() {
  const { state, start, end, sendText } = useCall();
  const inCall = isInCall(state.status);

  return (
    <main className="call-page">
      <header className="call-header">
        <h1>The Copper Pot</h1>
        <p className="subtitle">Voice reservations</p>
      </header>

      <CallControls status={state.status} mic={state.mic} onStart={start} onEnd={end} />
      {state.notice && (
        <p className="notice" role="status">
          {state.notice}
        </p>
      )}

      <Conversation lines={state.lines} />
      <DecisionPanel decision={state.decision} />
      <TextFallback
        inCall={inCall}
        canSend={canType(state.status)}
        maxLength={state.limits?.maxTextChars ?? DEFAULT_MAX_TEXT}
        onSend={sendText}
      />
    </main>
  );
}
