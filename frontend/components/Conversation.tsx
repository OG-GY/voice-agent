"use client";

import { useEffect, useRef } from "react";

import type { ConversationLine } from "@/lib/callController";

export function Conversation({ lines }: { lines: ConversationLine[] }) {
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest" });
  }, [lines.length]);

  return (
    <section className="conversation" aria-label="Conversation">
      <h2>Conversation</h2>
      {lines.length === 0 ? (
        <p className="muted">Press Start call to talk to The Copper Pot.</p>
      ) : (
        <ol>
          {lines.map((line) => (
            <li key={line.id} className={`line ${line.speaker}`}>
              <span className="who">{line.speaker === "bot" ? "Bot" : "You"}</span>
              <span className="text">{line.text}</span>
            </li>
          ))}
        </ol>
      )}
      <div ref={bottom} />
    </section>
  );
}
