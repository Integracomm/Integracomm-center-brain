import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

// base /spa/: os assets buildados são servidos pelo FastAPI em /spa/* — as
// ROTAS reais (/growth, /prevendas…) continuam no domínio raiz e o backend
// decide, rota a rota, se entrega o SPA ou o HTML antigo (migração gradual).
export default defineConfig({
  base: "/spa/",
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  build: { outDir: "dist", emptyOutDir: true },
  server: {
    port: 5173,
    // dev: encaminha API e login para o painel local (cookie same-origin via proxy)
    proxy: {
      "/api": "http://localhost:8000",
      "/login": "http://localhost:8000",
      "/logout": "http://localhost:8000",
    },
  },
});
