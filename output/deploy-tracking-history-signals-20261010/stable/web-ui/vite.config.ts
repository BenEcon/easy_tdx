import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vite.dev/config/
// dev server 把 /api 请求代理到后端 FastAPI（默认 8000 端口），
// 解决开发期跨域；生产环境由 FastAPI 同源托管 dist。
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
