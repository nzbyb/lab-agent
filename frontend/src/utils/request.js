import axios from 'axios'
import { getToken } from './auth'
import { useUserStore } from '@/stores/user'
import { pinia } from '@/stores'
import router from '@/router'
import { ElMessage } from 'element-plus'

const service = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  timeout: 60000
})

service.interceptors.request.use(
  (config) => {
    const token = getToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (err) => Promise.reject(err)
)

service.interceptors.response.use(
  (res) => {
    const data = res.data
    if (data.code !== 200) {
      // 401 单独处理，顺便修掉一个既有小 bug：改造前这里先弹 data.message、紧接着又弹
      // 一条「登录状态已失效」，同一个失败弹两条 toast。现在合并成一条更具体的提示。
      //
      // useUserStore(pinia) 显式传实例，不依赖 active pinia：这个文件在模块顶层只会
      // import 工厂函数（那时 app.use(pinia) 还没跑，顶层调用会抛 no active Pinia），
      // 真正的调用发生在拦截器函数体里，也就是请求发生时才执行，必然晚于 install。
      // 显式传实例让「active pinia 设过没有」这件事变得无关紧要。
      // 走 store 的 logout 而不是 utils/auth 的 logout：前者会把内存里的 userInfo 一起清掉。
      if (data.code === 401) {
        ElMessage.error('登录状态已失效，请重新登录')
        useUserStore(pinia).logout()
        router.push('/login')
        return Promise.reject(data)
      }
      ElMessage.error(data.message || '请求失败')
    }
    return data
  },
  (err) => {
    if (err.response) {
      const httpStatusCode = err.response.status
      if (httpStatusCode === 401) {
        // 把后端那句具体原因透出来。以前这条是静默的：人被踢回登录页却不知道为什么，
        // 只能猜是网络问题还是自己操作错了。现在服务端会因为好几种原因 401
        //（「密码已变更，请重新登录」「用户被禁用」「登录已失效」），说清楚最省事。
        ElMessage.error(err.response.data?.message || '登录已失效，请重新登录')
        useUserStore(pinia).logout()
        router.push('/login')
      } else {
        ElMessage.error(err.response.data?.message || '请求失败')
      }
    } else {
      ElMessage.error('网络异常，请检查后端服务')
    }
    return Promise.reject(err)
  }
)

export default service
