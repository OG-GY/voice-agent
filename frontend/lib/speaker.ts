// The bot's voice: the browser's built-in speech synthesis (browser only).
// Without speech synthesis the reply is still shown, just not spoken.

import type { Speaker } from "./callController";

const MS_PER_CHAR = 90; // generous estimate, for a safety timer
const SAFETY_EXTRA_MS = 3000;

export function createBrowserSpeaker(): Speaker {
  const synth = typeof window !== "undefined" && "speechSynthesis" in window ? window.speechSynthesis : null;
  let current: { cancelled: boolean; timer: ReturnType<typeof setTimeout> | null } | null = null;

  const cancel = (): void => {
    if (current) {
      current.cancelled = true;
      if (current.timer) clearTimeout(current.timer);
      current = null;
    }
    synth?.cancel();
  };

  return {
    speak(text, onDone) {
      cancel();
      if (!synth || !text.trim()) {
        onDone();
        return;
      }
      const job: { cancelled: boolean; timer: ReturnType<typeof setTimeout> | null } = {
        cancelled: false,
        timer: null,
      };
      current = job;
      const finish = () => {
        if (job.cancelled) return;
        job.cancelled = true;
        if (job.timer) clearTimeout(job.timer);
        if (current === job) current = null;
        onDone();
      };
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = "en-GB";
      utterance.onend = finish;
      utterance.onerror = finish;
      // Some browsers occasionally never fire `end`: never leave the call stuck in "speaking".
      job.timer = setTimeout(finish, text.length * MS_PER_CHAR + SAFETY_EXTRA_MS);
      synth.speak(utterance);
    },
    cancel,
  };
}
