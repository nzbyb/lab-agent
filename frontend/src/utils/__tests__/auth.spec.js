import { beforeEach, describe, expect, it } from 'vitest'

import {
  AI_LAST_CONVERSATION_PREFIX,
  getToken,
  getUserInfo,
  logout,
  removeToken,
  removeUserInfo,
  setToken,
  setUserInfo
} from '@/utils/auth'

// 这些用例全都围绕 localStorage。happy-dom 提供的是真实现（不是 mock），
// 所以「删没删掉」问的是环境本身，不是「我有没有调用 removeItem」。
beforeEach(() => {
  localStorage.clear()
})

describe('utils/auth.js 读写 localStorage', () => {
  it('从没登录过时两个读函数都回 null', () => {
    expect(getToken()).toBeNull()
    expect(getUserInfo()).toBeNull()
  })

  it('setToken / getToken 是一对，键名是 token', () => {
    setToken('tok-abc')
    expect(getToken()).toBe('tok-abc')
    // 直查底层字符串：路由守卫和请求拦截器读的都是这个键，
    // 哪天键名被改掉，只测 getToken 是会跟着一起错的（两边同源）。
    expect(localStorage.getItem('token')).toBe('tok-abc')
  })

  it('setUserInfo 存进去的是 JSON 文本，读回来是对象', () => {
    setUserInfo({ id: 1, role: 'admin' })
    // 断言序列化后的原文，而不是只断言能读回来：真出了「忘了 stringify」的错，
    // 存进去会变成 "[object Object]"，这时 getUserInfo 里的 JSON.parse 直接抛异常，
    // 而不是安静地返回一个错的东西。
    expect(localStorage.getItem('userInfo')).toBe('{"id":1,"role":"admin"}')
    expect(getUserInfo()).toEqual({ id: 1, role: 'admin' })
  })

  it('removeToken / removeUserInfo 各删各的，不互相牵连', () => {
    setToken('tok-abc')
    setUserInfo({ id: 1 })
    removeToken()
    expect(getToken()).toBeNull()
    expect(getUserInfo()).toEqual({ id: 1 })

    removeUserInfo()
    expect(getUserInfo()).toBeNull()
  })
})

describe('utils/auth.js 的 logout 清理范围', () => {
  it('token 和 userInfo 都被清掉', () => {
    setToken('tok-abc')
    setUserInfo({ id: 1, role: 'student' })
    logout()
    expect(getToken()).toBeNull()
    expect(getUserInfo()).toBeNull()
  })

  it('AI 会话记录（按用户 id 分名的那批）一并清掉', () => {
    localStorage.setItem(`${AI_LAST_CONVERSATION_PREFIX}1`, 'conv-1')
    localStorage.setItem(`${AI_LAST_CONVERSATION_PREFIX}2`, 'conv-2')
    logout()
    expect(localStorage.getItem(`${AI_LAST_CONVERSATION_PREFIX}1`)).toBeNull()
    expect(localStorage.getItem(`${AI_LAST_CONVERSATION_PREFIX}2`)).toBeNull()
  })

  it('前缀必须从头匹配，含相同子串的无关键不能误伤', () => {
    // 故意让这个键**包含**前缀但不以它开头。
    // 判据要是哪天从 startsWith 改成 includes，这条会红。
    localStorage.setItem(`x${AI_LAST_CONVERSATION_PREFIX}1`, 'keep-me')
    localStorage.setItem('someOtherAppKey', 'keep-me-too')
    logout()
    expect(localStorage.getItem(`x${AI_LAST_CONVERSATION_PREFIX}1`)).toBe('keep-me')
    expect(localStorage.getItem('someOtherAppKey')).toBe('keep-me-too')
  })
})
