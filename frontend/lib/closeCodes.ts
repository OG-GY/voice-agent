// What the page tells the caller for each close code and error code.
// The server's own error text is never shown: the page uses its own wording per code.

// Said whenever an established call is cut short: the restaurant follows up by phone.
const CALLBACK =
  "Our team will call you back in 2-3 minutes. Please answer that call and confirm your reservation.";

export const MESSAGES = {
  callEnded: "Call ended.",
  endedByServer: "The call was ended.",
  restarting: `The service is restarting. ${CALLBACK}`,
  busy: "We're busy right now. Please try again shortly.",
  policy: "The connection was closed by the server.",
  tooLarge: "That message was too large.",
  serverError: `Something went wrong on our side. ${CALLBACK}`,
  couldNotConnect: "Couldn't connect. Please try again.",
  disconnected: `The call was lost. ${CALLBACK}`,
  sttUnavailable: "Speech recognition isn't available: please type.",
  sayAgain: "Sorry, that didn't come through. Please say it again.",
  slowDown: "Slow down a little.",
  tooLong: "That was too long: please keep it shorter.",
  generic: "Something went wrong. Please try again.",
  echoOff: "Interrupting is off for this call (echo detected). Headphones help.",
  micBlocked: "Microphone blocked: you can type instead.",
  micUnavailable: "No microphone available here: you can type instead.",
} as const;

const ERROR_MESSAGES: Record<string, string> = {
  stt_unavailable: MESSAGES.sttUnavailable,
  stt_busy: MESSAGES.sayAgain,
  stt_timeout: MESSAGES.sayAgain,
  rate_limited: MESSAGES.slowDown,
  text_too_long: MESSAGES.tooLong,
  audio_too_long: MESSAGES.tooLong,
  audio_invalid: MESSAGES.generic,
  bad_json: MESSAGES.generic,
  unknown_type: MESSAGES.generic,
  service_unavailable: MESSAGES.generic,
};

export function describeError(code: string): string {
  return ERROR_MESSAGES[code] ?? MESSAGES.generic;
}

export interface CloseContext {
  /** A `ready` message was received on this connection. */
  ready: boolean;
  /** The server ended the call with a `turn` whose `ended` is true. */
  endedByServer: boolean;
}

/**
 * A failed connection before `ready` is reported as "couldn't connect": the browser can't
 * tell an origin or TLS refusal (refused before the handshake, seen as 1006) from a server
 * that is down or a network problem, so the page doesn't guess.
 */
export function describeClose(code: number, context: CloseContext): string {
  if (context.endedByServer) return MESSAGES.callEnded;
  switch (code) {
    case 1000:
      return MESSAGES.endedByServer;
    case 1001:
    case 1012:
      return MESSAGES.restarting;
    case 1013:
      return MESSAGES.busy;
    case 1008:
      return MESSAGES.policy;
    case 1009:
      return MESSAGES.tooLarge;
    case 1011:
      return MESSAGES.serverError;
    default:
      return context.ready ? MESSAGES.disconnected : MESSAGES.couldNotConnect;
  }
}
