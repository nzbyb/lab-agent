import { defineStore } from 'pinia'
import { getUserInfo, setToken, setUserInfo, logout as clearAuthStorage } from '@/utils/auth'

export const useUserStore = defineStore('user', {
  // 登录态的唯一事实源。改造前它是 @/utils/user.js 里一个模块作用域的 ref，
  // 那个文件已删除。
  //
  // token **不放** state：它仍只由 @/utils/auth 写进 localStorage，state 里再存一份
  // 就等于有两个 token 源、有机会不一致。所以这里只放 userInfo。
  // （注意区分：token 不进 state，但 saveLoginData 依然要把它写进 localStorage，
  // 那是登录能否生效的关键，见下面那个 action。）
  state: () => ({
    userInfo: getUserInfo()
  }),

  getters: {
    // 角色判据收敛到一处，一律精确匹配 admin，兜底落到最小权限侧。
    // 不能写成「非 student 即管理员」：token 在而 userInfo 缺失时 role 是 undefined，
    // 那样会把一个未知身份渲染成管理员视图、并给出四条管理入口（点进去被守卫拦到 403，
    // 403 的「返回首页」又 push 回这张管理首页，来回往复）。
    // 兜底方向与 Layout.vue、Profile.vue（显式回落「未知角色」）
    // 以及后端 get_reservation_page_list 那句 `role != "admin"` 对齐。
    isAdmin: (state) => state.userInfo?.role === 'admin',
    isStudent: (state) => state.userInfo?.role === 'student',
    roleLabel: (state) => {
      if (state.userInfo?.role === 'admin') return '管理员'
      if (state.userInfo?.role === 'student') return '学生'
      return '未知角色'
    },
    // 这个数字的含义是随角色变的：后端 get_reservation_page_list 只对**非 admin**
    // 按 user_id 过滤，统计接口 /api/statistics/overview 沿用同一口径，所以学生拿到的
    // 是"我的预约数"，管理员拿到的是"全库预约总数"。文案必须跟着一起变，否则管理员会把
    // 全库总数当成自己的。判据刻意和后端那句 `role != "admin"` 对齐，以后加新角色也不会错位。
    reservationCountLabel: (state) =>
      state.userInfo?.role === 'admin' ? '全部预约' : '与我相关的预约'
  },

  actions: {
    // 登录成功：token 写 localStorage，用户信息同时写 localStorage 和 state。
    // setToken 这一句不能省——漏了它登录后拿不到 token，路由守卫会立刻把人踢回登录页。
    saveLoginData(data) {
      setToken(data.token)
      setUserInfo(data.user)
      this.userInfo = data.user
    },
    // 改完个人资料后同步，语义与改造前的 updateUser 完全一致
    updateUser(user) {
      setUserInfo(user)
      this.userInfo = user
    },
    // 从 localStorage 重新读一份（改造前就有，语义不变）
    reloadUser() {
      this.userInfo = getUserInfo()
    },
    // 退出登录。除了清 localStorage，**必须把内存里这份也清掉**：
    // 改造前 utils/auth.logout() 只清 localStorage，模块级的 userInfo ref 原封不动，
    // 于是退出后侧边栏菜单和页头头像要整页刷新才会消失。这就是引入 Pinia 要修的既有缺陷。
    logout() {
      clearAuthStorage()
      this.userInfo = null
    }
  }
})
