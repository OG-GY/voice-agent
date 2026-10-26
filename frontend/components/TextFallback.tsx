"use client";

import { useState, type FormEvent } from "react";

interface Props {
  inCall: boolean;
  /** False while a request is in flight: text is never queued. */
  canSend: boolean;
  maxLength: number;
  onSend: (text: string) => boolean;
}

export function TextFallback({ inCall, canSend, maxLength, onSend }: Props) {
  const [text, setText] = useState("");

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (canSend && onSend(text)) setText(""); // keep the text if it wasn't sent
  }

  return (
    <form className="text-input" onSubmit={submit}>
      <label htmlFor="say" className="visually-hidden">
        Type a message
      </label>
      <input
        id="say"
        value={text}
        onChange={(event) => setText(event.target.value)}
        placeholder={inCall ? "Type instead…" : "Start a call to type"}
        maxLength={maxLength}
        disabled={!inCall}
        autoComplete="off"
      />
      <button type="submit" className="button" disabled={!inCall || !canSend || !text.trim()}>
        Send
      </button>
    </form>
  );
}
