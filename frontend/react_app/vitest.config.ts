import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  // tsconfig sets `"jsx": "preserve"` for Next.js, which leaves the JSX in the
  // test files untransformed. Tell Vite's transformer (oxc since Vite 8) to
  // use the automatic runtime so vitest can run components that don't import
  // React explicitly.
  oxc: { jsx: { runtime: "automatic" } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
});
