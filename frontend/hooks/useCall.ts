"use client";

// React adapter for the CallController. The controller's constructor touches no browser
// API, so this is safe during server rendering; socket, microphone and speaker are only
// created by start(), which runs from the Start button.

import { useEffect, useState, useSyncExternalStore } from "react";

import { CallController, type CallState } from "@/lib/callController";
import { createBrowserSocket } from "@/lib/callSocket";
import { BARGE_IN_DEFAULT, wsUrl } from "@/lib/config";
import { createMicRecorder } from "@/lib/recorder";
import { createBrowserSpeaker } from "@/lib/speaker";

export interface UseCall {
  state: CallState;
  start: () => void;
  end: () => void;
  sendText: (text: string) => boolean;
}

export function useCall(): UseCall {
  const [controller] = useState(
    () =>
      new CallController({
        url: wsUrl(),
        createSocket: createBrowserSocket,
        createSpeaker: createBrowserSpeaker,
        createRecorder: createMicRecorder,
        bargeIn: BARGE_IN_DEFAULT,
      }),
  );
  const state = useSyncExternalStore(controller.subscribe, controller.getState, controller.getState);

  useEffect(() => {
    // Leaving the page or unmounting ends the call. shutdown() is idempotent, so React's
    // development double-run of effects is harmless.
    const onPageHide = () => controller.shutdown();
    window.addEventListener("pagehide", onPageHide);
    return () => {
      window.removeEventListener("pagehide", onPageHide);
      controller.shutdown();
    };
  }, [controller]);

  return {
    state,
    start: () => controller.start(),
    end: () => controller.end(),
    sendText: (text) => controller.sendText(text),
  };
}
