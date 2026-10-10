import { defineConfig } from '../../web-ui/node_modules/vite/dist/node/index.js'
import vue from '../../web-ui/node_modules/@vitejs/plugin-vue/dist/index.mjs'
import { fileURLToPath } from 'node:url'
const project = fileURLToPath(new URL('../../', import.meta.url))
export default defineConfig({
  root: fileURLToPath(new URL('.', import.meta.url)),
  plugins: [vue()],
  resolve: { alias: { vue: project + 'web-ui/node_modules/vue/dist/vue.esm-bundler.js' } },
  server: { host: '127.0.0.1', port: 18093, strictPort: true, fs: { allow: [project] } },
})
