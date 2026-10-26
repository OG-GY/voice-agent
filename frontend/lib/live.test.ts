// Optional end-to-end check against a running backend, using the real WebSocket adapter.
// Skipped unless LIVE_WS_URL is set, e.g.
//   $env:LIVE_WS_URL = "ws://127.0.0.1:8000/ws/call"; npx vitest run lib/live.test.ts

import { describe, expect, it } from "vitest";

import { CallController, type CallState } from "./callController";
import { createBrowserSocket } from "./callSocket";

const url = process.env.LIVE_WS_URL;

async function waitFor(controller: CallController, ok: (s: CallState) => boolean, ms = 5000): Promise<void> {
  const deadline = Date.now() + ms;
  while (!ok(controller.getState())) {
    if (Date.now() > deadline) throw new Error(`timed out in state ${controller.getState().status}`);
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
}

describe.skipIf(!url)("live backend", () => {
  it("runs a text call from greeting to hang-up", async () => {
    const controller = new CallController({ url: url as string, createSocket: createBrowserSocket });
    controller.start();
    await waitFor(controller, (s) => s.status === "listening");
    expect(controller.getState().lines[0].text).toContain("Copper Pot");

    expect(controller.sendText("what are your timings")).toBe(true);
    await waitFor(controller, (s) => s.status === "listening");
    expect(controller.getState().lines.at(-1)?.text.toLowerCase()).toContain("open");
    expect(controller.getState().decision?.intent).toBe("faq_hours");

    controller.end();
    expect(controller.getState().status).toBe("ended");
  });
});
