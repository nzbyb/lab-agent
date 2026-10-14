import { beforeEach, describe, expect, it, vi } from 'vitest'

// axios 整包替掉，只为一件事：把 request.js 注册的那两个拦截器函数捞出来。
//
// 不采用 service.interceptors.response.handlers[0] 那种写法 —— 那是 axios 的私有字段，
// 升一次级就可能改名，测试会以「读不到 handlers」的形式红，而不是以「行为变了」的形式红。
// 这里让 axios.create 返回一个只记账的假实例，捞函数的方式就钉死在公开的
// interceptors.*.use(两个回调) 这个签名上。
vi.mock('axios', () => {
  const request = []
  const response = []
  const instance = {
    interceptors: {
      request: { use: (onFulfilled, onRejected) => request.push({ onFulfilled, onRejected }) },
      response: { use: (onFulfilled, onRejected) => response.push({ onFulfilled, onRejected }) }
    }
  }
  return {
    default: {
      create: () => instance,
      __interceptors: { request, response }
    }
  }
})

vi.mock('element-plus', () => ({ ElMessage: { error: vi.fn(), success: vi.fn() } }))
vi.mock('@/router', () => ({ default: { push: vi.fn() } }))

import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'

import { pinia } from '@/stores'
import { useUserStore } from '@/stores/user'
import { getToken } from '@/utils/auth'

// 副作用导入：这个模块一加载就把两个拦截器注册进（假的）axios 里。
// 必须放在上面那堆 vi.mock 之后 —— vi.mock 会被提升到文件最顶部，
// 所以这里顺序其实怎么写都对，但摆在后面读起来最不容易误会。
import '@/utils/request'

const reqInterceptors = axios.__interceptors.request[0]
const respInterceptors = axios.__interceptors.response[0]

beforeEach(() => {
  localStorage.clear()
  // store 是按 pinia 实例单例的，会带着上一个用例的状态活到下一个用例。
  // $reset() 会重跑 state()，也就是重新读一次（此刻已清空的）localStorage。
  useUserStore(pinia).$reset()
})

describe('请求拦截器：自动带上 token', () => {
  it('有 token 时塞进 Authorization 头', () => {
    localStorage.setItem('token', 'tok-123')
    const config = reqInterceptors.onFulfilled({ headers: {} })
    expect(config.headers.Authorization).toBe('Bearer tok-123')
  })

  it('没有 token 时什么都不塞', () => {
    const config = reqInterceptors.onFulfilled({ headers: {} })
    // 少了 if (token) 这层判断的话，这里会变成字面量 "Bearer null"，
    // 后端收到一个长得像 token 的垃圾串，报的错跟「没登录」完全两样。
    expect(config.headers.Authorization).toBeUndefined()
  })
})

describe('响应拦截器：业务码不是 200 时', () => {
  it('code 200 静默放行，一个 toast 都不弹', () => {
    const body = { code: 200, data: { list: [] } }
    // 成功这条路是**同步返回**的（不是返回 promise），所以断言直接拿返回值比。
    expect(respInterceptors.onFulfilled({ data: body })).toBe(body)
    expect(ElMessage.error).not.toHaveBeenCalled()
    expect(router.push).not.toHaveBeenCalled()
  })

  it('code 401：弹一条 toast、清登录态、踢回登录页，然后 reject', async () => {
    const store = useUserStore(pinia)
    store.saveLoginData({ token: 'tok-abc', user: { id: 1, role: 'student' } })
    // 前置条件：不清掉一个本来就是空的登录态，后面那三条断言等于没测。
    expect(store.userInfo).not.toBeNull()

    const body = { code: 401, message: '登录已失效' }
    const result = respInterceptors.onFulfilled({ data: body })
    await expect(result).rejects.toEqual(body)

    // 这条是既有 bug 的守门员：改造前这里先弹 data.message，紧接着又弹一条
    // 「登录状态已失效」，同一次失败弹两条 toast。断言次数才抓得住它。
    expect(ElMessage.error).toHaveBeenCalledTimes(1)
    expect(ElMessage.error).toHaveBeenCalledWith('登录状态已失效，请重新登录')

    // 走的是 store 的 logout，不是 utils/auth 那个只清 localStorage 的。
    // 断言内存这份 —— 只查 localStorage 的话两种写法都过，等于没测。
    expect(store.userInfo).toBeNull()
    expect(getToken()).toBeNull()
    expect(router.push).toHaveBeenCalledWith('/login')
  })

  it('其它业务错误码：弹后端给的文案，然后把 body 原样交回调用方', () => {
    const body = { code: 500, message: '用户名已存在' }
    // 注意这里是**返回** body 而不是抛：调用方拿到响应体后自己看 res.code。
    // 这一点跟上面 401 那条正好相反（那条是 reject），别把两者写成一样。
    expect(respInterceptors.onFulfilled({ data: body })).toBe(body)

    expect(ElMessage.error).toHaveBeenCalledTimes(1)
    expect(ElMessage.error).toHaveBeenCalledWith('用户名已存在')
    // 业务错误不该把人踢下线 —— 后端把业务错误包在 HTTP 200 里，
    // 这不是「登录失效」那条路。
    expect(router.push).not.toHaveBeenCalled()
  })

  it('后端没给 message 时回落到通用文案', () => {
    respInterceptors.onFulfilled({ data: { code: 500 } })
    expect(ElMessage.error).toHaveBeenCalledWith('请求失败')
  })
})

describe('响应拦截器：HTTP 层报错时', () => {
  it('HTTP 401：把后端那句具体原因透出来，并清登录态', async () => {
    const store = useUserStore(pinia)
    store.saveLoginData({ token: 'tok-abc', user: { id: 1, role: 'student' } })
    expect(store.userInfo).not.toBeNull()

    const err = { response: { status: 401, data: { message: '密码已变更，请重新登录' } } }
    await expect(respInterceptors.onRejected(err)).rejects.toBe(err)

    // 后端因为好几种原因回 401（密码变了 / 被禁用 / 令牌过期），
    // 把服务端那句话透出来，人才知道自己为什么被踢回登录页。
    expect(ElMessage.error).toHaveBeenCalledWith('密码已变更，请重新登录')
    expect(store.userInfo).toBeNull()
    expect(router.push).toHaveBeenCalledWith('/login')
  })

  it('HTTP 401 但后端没给 message：回落到通用文案', async () => {
    const err = { response: { status: 401, data: {} } }
    await expect(respInterceptors.onRejected(err)).rejects.toBe(err)
    expect(ElMessage.error).toHaveBeenCalledWith('登录已失效，请重新登录')
  })

  it('HTTP 500：只弹提示，不清登录态也不跳转', async () => {
    const store = useUserStore(pinia)
    store.saveLoginData({ token: 'tok-abc', user: { id: 1, role: 'student' } })

    const err = { response: { status: 500, data: { message: '服务器内部错误' } } }
    await expect(respInterceptors.onRejected(err)).rejects.toBe(err)

    expect(ElMessage.error).toHaveBeenCalledWith('服务器内部错误')
    expect(store.userInfo).not.toBeNull()
    expect(router.push).not.toHaveBeenCalled()
  })

  it('压根没有 err.response（断网 / 超时）：提示去查后端服务', async () => {
    const err = new Error('Network Error')
    await expect(respInterceptors.onRejected(err)).rejects.toBe(err)
    // 这条路以前是静默的：请求发不出去，界面上什么都不显示。
    expect(ElMessage.error).toHaveBeenCalledWith('网络异常，请检查后端服务')
  })
})
