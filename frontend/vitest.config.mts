import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

// Unit tests run in Node: the browser APIs sit behind ports that the tests replace with fakes.
export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./", import.meta.url)) },
  },
  test: {
    environment: "node",
    include: ["lib/**/*.test.ts"],
  },
});
