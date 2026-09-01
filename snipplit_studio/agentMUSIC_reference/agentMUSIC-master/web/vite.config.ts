import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, '');
  const devServerPort = Number(env.VITE_DEV_SERVER_PORT || 5174);
  const apiProxyTarget = env.VITE_API_PROXY_TARGET || 'http://localhost:8080';

  return {
    plugins: [react()],
    base: '/static/',
    build: {
      outDir: path.resolve(__dirname, '../static'),
      emptyOutDir: true,
      sourcemap: false,
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (id.includes('node_modules/react') || id.includes('node_modules/react-dom')) {
              return 'react';
            }
            if (id.includes('node_modules/@tanstack/react-query')) {
              return 'query';
            }
            return undefined;
          },
        },
      },
    },
    server: {
      port: devServerPort,
      proxy: {
        '/api': apiProxyTarget,
      },
    },
  };
});
