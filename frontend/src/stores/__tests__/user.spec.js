import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useUserStore } from '@/stores/user'
import { getToken, setToken, setUserInfo } from '@/utils/auth'

// 每个用例一套全新的 pinia + 空的 localStorage。
//
// 顺序很关键：store 的 state 是在**创建那一刻**读 localStorage 的
//（state: () => ({ userInfo: getUserInfo() })），所以必须先摆好 storage 再 useUserStore()。
// 反过来的话读到的是上一个用例留下的东西。
function freshStore({ user, token } = {}) {
  localStorage.clear()
  setActivePinia(createPinia())
  if (token) setToken(token)
  if (user) setUserInfo(user)
  return useUserStore()
}

beforeEach(() => {
  localStorage.clear()
})

describe('stores/user.js 的初始状态', () => {
  it('localStorage 里没有用户信息时是 null', () => {
    expect(freshStore().userInfo).toBeNull()
  })

  it('localStorage 里有用户信息时能读出来（刷新页面还记得登录）', () => {
    const store = freshStore({ user: { id: 7, name: '张三', role: 'student' } })
    expect(store.userInfo).toEqual({ id: 7, name: '张三', role: 'student' })
  })
})

describe('stores/user.js 的 action', () => {
  it('saveLoginData 必须把 token 写进 localStorage', () => {
    const store = freshStore()
    store.saveLoginData({ token: 'tok-xyz', user: { id: 1, role: 'admin' } })

    // 这条是踩过的坑的守门员：store 的 state 里**不放** token（避免两个 token 源），
    // 于是很容易顺手把 setToken 一起省掉 —— 那样登录看着成功，
    // 但 token 永远到不了 localStorage，路由守卫立刻把人弹回登录页。
    expect(getToken()).toBe('tok-xyz')
    expect(store.userInfo).toEqual({ id: 1, role: 'admin' })
  })

  it('saveLoginData 同时写内存和 localStorage', () => {
    const store = freshStore()
    store.saveLoginData({ token: 't', user: { id: 2, role: 'student' } })
    expect(store.userInfo).toEqual({ id: 2, role: 'student' })
    expect(JSON.parse(localStorage.getItem('userInfo'))).toEqual({ id: 2, role: 'student' })
  })

  it('updateUser 两边都更新，但不动 token', () => {
    const store = freshStore({ token: 'tok-keep', user: { id: 3, name: '旧名' } })
    store.updateUser({ id: 3, name: '新名' })
    expect(store.userInfo).toEqual({ id: 3, name: '新名' })
    expect(JSON.parse(localStorage.getItem('userInfo'))).toEqual({ id: 3, name: '新名' })
    expect(getToken()).toBe('tok-keep')
  })

  it('reloadUser 从 localStorage 重读一份', () => {
    const store = freshStore({ user: { id: 4, name: '原来的' } })
    // 绕过 store 直接改 storage，模拟「别的标签页把它改了」
    setUserInfo({ id: 4, name: '被别处改过的' })
    store.reloadUser()
    expect(store.userInfo).toEqual({ id: 4, name: '被别处改过的' })
  })

  it('logout 必须把内存里那份也清掉', () => {
    const store = freshStore({ token: 'tok-abc', user: { id: 5, role: 'admin' } })
    store.logout()

    // 这就是引入 Pinia 要修的那个既有缺陷：改造前 logout 只清 localStorage，
    // 模块作用域里的 userInfo 原封不动，于是退出后侧边栏菜单和页头头像
    // 要整页刷新才会消失。只断言 localStorage 是抓不住它的。
    expect(store.userInfo).toBeNull()
    expect(getToken()).toBeNull()
    expect(localStorage.getItem('userInfo')).toBeNull()
  })
})

describe('stores/user.js 的角色判据', () => {
  it('admin 认得出是管理员', () => {
    const store = freshStore({ user: { id: 1, role: 'admin' } })
    expect(store.isAdmin).toBe(true)
    expect(store.isStudent).toBe(false)
    expect(store.roleLabel).toBe('管理员')
  })

  it('student 认得出是学生', () => {
    const store = freshStore({ user: { id: 1, role: 'student' } })
    expect(store.isAdmin).toBe(false)
    expect(store.isStudent).toBe(true)
    expect(store.roleLabel).toBe('学生')
  })

  it('role 缺失时一律按最小权限兜底，不能当成管理员', () => {
    const store = freshStore({ user: { id: 1 } })
    // 判据写成「非 student 即管理员」的话这条会红。那种写法在
    // 「有 token 但 userInfo 读不出来」时会渲染出管理员视图 + 四条管理菜单，
    // 点进去被守卫拦到 403，403 的「返回首页」又是那张管理首页，来回往复。
    expect(store.isAdmin).toBe(false)
    expect(store.roleLabel).toBe('未知角色')
  })

  it('认不出来的角色也按最小权限兜底', () => {
    const store = freshStore({ user: { id: 1, role: 'teacher' } })
    expect(store.isAdmin).toBe(false)
    expect(store.isStudent).toBe(false)
    expect(store.roleLabel).toBe('未知角色')
  })
})

describe('stores/user.js 的统计口径文案', () => {
  it('管理员看到的是全库总数，文案写「全部预约」', () => {
    expect(freshStore({ user: { id: 1, role: 'admin' } }).reservationCountLabel).toBe('全部预约')
  })

  it('非管理员看到的是自己的，文案写「与我相关的预约」', () => {
    expect(freshStore({ user: { id: 1, role: 'student' } }).reservationCountLabel).toBe(
      '与我相关的预约'
    )
  })

  it('角色缺失时文案跟非管理员一致', () => {
    // 文案和 isAdmin 必须用同一个判据。两边不一致时，管理员会看到
    // 「与我相关的预约」配着全库数字——这正是首页那个假统计的老毛病。
    expect(freshStore({ user: { id: 1 } }).reservationCountLabel).toBe('与我相关的预约')
  })
})
