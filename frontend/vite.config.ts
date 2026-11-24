import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import Components from 'unplugin-vue-components/vite'
import { AntDesignVueResolver } from 'unplugin-vue-components/resolvers'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '');
  const proxyTarget = env.VITE_API_PROXY_TARGET || 'http://localhost:8084';

  const proxy = {
    '/api': {
      target: proxyTarget,
      changeOrigin: true,
    },
  };

  return {
    plugins: [
      vue(),
      Components({
        dts: 'src/components.d.ts',
        resolvers: [AntDesignVueResolver({ importStyle: false })],
      }),
    ],
    server: { proxy },
    preview: { proxy },
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            if (!id.includes('node_modules')) return;
            if (id.includes('@vue-flow')) return 'vue-flow';
            if (id.includes('vue-router') || id.includes('pinia') || id.includes('/vue/') || id.includes('@vue/')) return 'vue';
          },
        },
      },
    },
  };
})
