import react from "@vitejs/plugin-react"
import { defineConfig } from "vitest/config"

const apiProxy = {
  "/api": {
    target: "http://127.0.0.1:8091",
    changeOrigin: true,
  },
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 4178,
    strictPort: true,
    proxy: apiProxy,
  },
  preview: {
    host: "0.0.0.0",
    port: 4178,
    strictPort: true,
    proxy: apiProxy,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
})
