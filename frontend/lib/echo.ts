// Did an "interruption" really hear the bot's own voice coming back through the speakers?
//
// An echo is a stretch of what the bot was saying, so most of its word PAIRS appear in the
// reply. Single shared words don't count: a caller answering "a window table please" reuses
// words from the question without echoing it. (Word pairs: "a window", "window table", ...)

const OVERLAP = 0.6; // share of the heard word pairs that must come from the bot's reply
const MIN_WORDS = 3; // shorter, non-empty speech is treated as a real person

const words = (text: string): string[] =>
  text
    .toLowerCase()
    .replace(/[^a-z0-9'\s]/g, " ")
    .split(/\s+/)
    .filter(Boolean);

const pairs = (list: string[]): string[] => list.slice(1).map((word, i) => `${list[i]} ${word}`);

/** True when the heard text is empty (nothing usable) or mostly a copy of the spoken reply. */
export function isSuspectedEcho(transcript: string, spokenReply: string): boolean {
  const heard = words(transcript);
  if (heard.length === 0) return true;
  if (heard.length < MIN_WORDS) return false;
  const spoken = new Set(pairs(words(spokenReply)));
  const heardPairs = pairs(heard);
  const matching = heardPairs.filter((pair) => spoken.has(pair)).length;
  return matching / heardPairs.length >= OVERLAP;
}
