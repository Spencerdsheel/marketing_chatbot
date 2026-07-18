import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/**
 * jsdom environment (decision 6): supports attachShadow, a
 * document.currentScript-style script lookup, and fetch mocking — enough
 * for S14.1's unit scope (config parsing, admission fetch, shadow-root
 * attach + mount idempotency). True cross-origin CORS + hostile-page style
 * isolation are proven by the manual host-page walkthrough instead
 * (dev/README.md), per the phase's stated test method.
 */
export default defineConfig({
  plugins: [react()],
  define: {
    // Mirrors vite.config.ts's build-time define so config.ts's reference
    // to __WIDGET_API_BASE__ resolves under Vitest too.
    __WIDGET_API_BASE__: JSON.stringify("http://localhost:8000"),
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    exclude: ["node_modules", "dist"],
    globals: false,
  },
});
