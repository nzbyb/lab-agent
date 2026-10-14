import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { configDefaults, defineConfig } from 'vitest/config'

// 刻意**不**去 mergeConfig(vite.config.js)：那份配置挂了 vite-plugin-vue-devtools，
// 那是给浏览器里调试用的，跑测试时既没用、又可能反过来干扰。
// 别名在这儿重写了一遍——只有一条，重复的维护成本远小于「测试环境和开发环境不一致」
// 这种要查半天的窟窿。
//
// @vitejs/plugin-vue 现在还用不上（被测的三个模块都不 import .vue）。
// 留着是因为少了它，以后第一次写组件测试时会撞上一句很难懂的
// "Failed to parse source ... .vue"，而那正是最容易让人放弃加测试的时刻。
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  test: {
    // happy-dom 负责提供 localStorage —— 被测的三个模块全都读写它。
    // 不用 jsdom：这里不需要真实渲染和布局，happy-dom 起得更快。
    environment: 'happy-dom',
    exclude: [...configDefaults.exclude],
    // 每个用例之间把 mock 的调用记录清空（只清记录，不清实现），
    // 否则「弹了几条 toast」这类断言会带上前一个用例的账。
    clearMocks: true
  }
})
