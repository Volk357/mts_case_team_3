import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { loadEnv } from "vite";
import { defineConfig } from "vitest/config";

export default defineConfig(({ mode }) => {
  const environment = loadEnv(mode, ".", "VITE_");

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        "@": new URL("./src", import.meta.url).pathname,
      },
    },
    server: {
      port: 5173,
      proxy: {
        "/api": environment.VITE_DEV_API_PROXY_TARGET ?? "http://127.0.0.1:8000",
      },
    },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test/setup.ts"],
      coverage: {
        provider: "v8",
        reporter: ["text", "html"],
        include: ["src/**/*.{ts,tsx}"],
        exclude: ["src/main.tsx", "src/test/**", "src/components/ui/**"],
      },
    },
  };
});
