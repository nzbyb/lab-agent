import { createPinia } from 'pinia'

// 单独把这个实例导出，是为了让 @/utils/request.js 能显式传进 useUserStore(pinia)。
// 那个文件在模块顶层拿不到 active pinia（那时 app.use(pinia) 还没执行），
// 显式传实例是最稳的写法，见 request.js 里的注释。
export const pinia = createPinia()
