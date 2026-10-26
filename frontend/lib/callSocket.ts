// The real WebSocket behind the controller's socket port.
// It only touches `WebSocket` when called, which happens from start() in the browser.

import type { SocketFactory } from "./callController";

export const createBrowserSocket: SocketFactory = (url, handlers) => {
  const ws = new WebSocket(url);
  ws.binaryType = "arraybuffer";
  ws.onopen = () => handlers.onOpen();
  ws.onmessage = (event: MessageEvent) => handlers.onMessage(event.data);
  ws.onerror = () => handlers.onError();
  ws.onclose = (event: CloseEvent) => handlers.onClose(event.code);

  return {
    send: (data) => {
      if (ws.readyState === WebSocket.OPEN) ws.send(data);
    },
    isOpen: () => ws.readyState === WebSocket.OPEN,
    close: () => {
      // Detach first: after we close it ourselves, its events are of no interest.
      ws.onopen = null;
      ws.onmessage = null;
      ws.onerror = null;
      ws.onclose = null;
      if (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN) ws.close(1000);
    },
  };
};
