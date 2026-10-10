import { getToken, getUserInfo } from '@/utils/auth'
import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', redirect: '/manager/home' },
    {
      path: '/manager',
      name: 'Layout',
      component: () => import('@/layouts/Layout.vue'),
      children: [
        { path: 'home', name: 'Home', component: () => import('@/views/Home.vue') },
        { path: 'profile', name: 'Profile', component: () => import('@/views/Profile.vue') },
        { path: 'password', name: 'Password', component: () => import('@/views/Password.vue') },
        { path: 'lab-list', name: 'LabList', component: () => import('@/views/LabList.vue') },
        {
          path: 'lab-equipment',
          name: 'LabEquipment',
          component: () => import('@/views/LabEquipment.vue')
        },
        {
          path: 'my-reservation',
          name: 'MyReservation',
          component: () => import('@/views/MyReservation.vue')
        },
        { path: 'ai-chat', name: 'AIChat', component: () => import('@/views/AIChat.vue') },

        // 下面这 4 条的 meta.role 名单，跟后端 dependencies/auth.py 里
        // get_current_admin 的名单严格一致：后端只允许 admin 调用的那几组接口，
        // 前端就不放非 admin 进页面。
        // 前端守卫只是体验层，不是安全边界——绕过它顶多多看到一个空壳页面，
        // 真正的拦截在后端的依赖注入里。
        {
          path: 'lab',
          name: 'Lab',
          component: () => import('@/views/Lab.vue'),
          meta: { role: 'admin' }
        },
        {
          path: 'equipment',
          name: 'Equipment',
          component: () => import('@/views/Equipment.vue'),
          meta: { role: 'admin' }
        },
        {
          path: 'audit-reservation',
          name: 'AuditReservation',
          component: () => import('@/views/AuditReservation.vue'),
          meta: { role: 'admin' }
        },
        {
          path: 'user',
          name: 'User',
          component: () => import('@/views/User.vue'),
          meta: { role: 'admin' }
        },

        { path: '403', name: 'Forbidden', component: () => import('@/views/Forbidden.vue') }
      ]
    },
    { path: '/login', name: 'Login', component: () => import('@/views/Login.vue') },
    { path: '/register', name: 'Register', component: () => import('@/views/Register.vue') },
    // 兜底路由必须放最后：前面所有路径都没匹配上才轮到它。
    // 改造前没有这条，任何拼错的地址（比如菜单里写错的 /manager/lablist）都会
    // 渲染成一片空白，看起来像"点了没反应"。
    {
      path: '/:pathMatch(.*)*',
      name: 'NotFound',
      component: () => import('@/views/NotFound.vue')
    }
  ]
})

router.beforeEach((to) => {
  // 登录页和注册页本身不需要登录态
  if (to.path === '/login' || to.path === '/register') {
    return true
  }
  if (!getToken()) {
    return '/login'
  }
  const needRole = to.meta?.role
  if (needRole && getUserInfo()?.role !== needRole) {
    return '/manager/403'
  }
  return true
})

export default router
