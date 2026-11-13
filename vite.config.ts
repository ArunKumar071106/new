import { defineConfig, type PluginOption } from 'vite';
import react from '@vitejs/plugin-react';
import basicSsl from '@vitejs/plugin-basic-ssl';

// WebXR requires a secure context. `localhost` counts as secure; a phone on the LAN does
// not, so `npm run dev:https` serves over HTTPS with a self-signed certificate.
const useHttps = process.env.HTTPS === '1';
const plugins: PluginOption[] = [react()];
if (useHttps) plugins.push(basicSsl());

export default defineConfig({
  plugins,
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  preview: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: { chunkSizeWarningLimit: 900 },
});
