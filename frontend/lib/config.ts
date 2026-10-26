// Public configuration. NEXT_PUBLIC_* values are inlined into the browser bundle at build
// time, so they must never hold a secret. The variable must be written out literally for
// Next.js to inline it.

const DEFAULT_WS_URL = "ws://localhost:8000/ws/call";

/**
 * Let callers talk over the bot. If it turns out to be unreliable (the bot hears itself),
 * set this to false: the microphone is then muted while the bot speaks, as in step 3.
 * (The call also switches itself to that mode if it detects echo twice in a row.)
 */
export const BARGE_IN_DEFAULT = true;

export function wsUrl(): string {
  return process.env.NEXT_PUBLIC_WS_URL || DEFAULT_WS_URL;
}
