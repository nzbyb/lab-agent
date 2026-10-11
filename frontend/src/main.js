import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import { pinia } from '@/stores'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
// 补上中文语言包导入
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'
import '@/assets/css/global.css'

const app = createApp(App)

// pinia 必须在 router 之前：路由守卫虽然只读 localStorage，但页面组件一挂载就会用到
// store，早装一步省得依赖执行顺序的巧合。
app.use(pinia)
app.use(router)
app.use(ElementPlus, {
  locale: zhCn
})
//全局注册图标
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.mount('#app')
