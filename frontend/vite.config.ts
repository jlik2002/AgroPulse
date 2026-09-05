import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// Прокси на бэкенд нужен только в режиме разработки: в собранном образе
// тот же путь /api раздаёт nginx, поэтому адрес API нигде не хардкодится.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      output: {
        // Карта и графики весят больше остального кода вместе взятого.
        // Отдельные чанки позволяют браузеру кэшировать их между сборками.
        manualChunks: {
          echarts: ["echarts", "echarts/core", "echarts/charts", "echarts/components"],
          leaflet: ["leaflet", "react-leaflet", "@geoman-io/leaflet-geoman-free"],
        },
      },
    },
  },
});
