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
    // 文件下载（目前只有报表导出）单独一条分支：成功时 res.data 是 Blob，
    // 没有 code 字段，落到下面那句判断会被当成"请求失败"。
    // 失败时后端回的是 JSON 而不是文件，这里读出来弹提示，
    // 否则用户会下载到一个内容其实是报错信息的 .xlsx。
    // config 用可选链：拦截器的单测会直接塞一个只有 data 的假对象进来，
    // 拿不到 config 时按普通 JSON 响应处理即可。
    if (res.config?.responseType === 'blob') {
      const blob = res.data
      if (blob && blob.type && blob.type.includes('application/json')) {
        return blob.text().then((text) => {
          let body = {}
          try {
            body = JSON.parse(text)
          } catch {
            // 不是合法 JSON 就按通用错误处理
          }
          ElMessage.error(body.message || '导出失败')
          return Promise.reject(body)
        })
      }
      return res
    }

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
