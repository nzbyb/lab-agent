<template>
  <!-- 外层横向：左边整条深色侧栏，右边上下两段（页头 + 内容）。
       改造前侧栏在页头下面、页头横贯整屏，两栏都是白的，和内容区的白卡片
       连成一片，看不出"导航"和"内容"的边界。深色侧栏一次解决这个问题，
       而且不用动任何页面内部的结构。 -->
  <el-container class="layout-root">
    <!-- 同一块 DOM 换形态：桌面端是左边固定的侧栏，窄屏下是从左侧滑出的抽屉。
         不做成两套菜单，是为了避免两份菜单项各自维护、加一项漏一边。 -->
    <el-aside class="layout-aside" :class="{ 'is-open': menuOpen }" width="232px">
      <div class="layout-brand">
        <img src="@/assets/imgs/logo.svg" alt="Logo" class="layout-logo" />
        <!-- 标题拆成两行：主标题说是什么系统，副标题说它管什么。
             只放一行 24px 的长中文名，在 232px 的侧栏里会被挤到换行。 -->
        <div class="layout-brand-text">
          <span class="layout-brand-name">智能实验室</span>
          <span class="layout-brand-sub">预约管理系统</span>
        </div>
      </div>

      <el-menu
        router
        :default-active="router.currentRoute.value.path"
        class="layout-menu"
        @select="onMenuSelect"
      >
        <el-menu-item index="/manager/home">
          <el-icon><icon-menu /></el-icon>
          <span>系统首页</span>
        </el-menu-item>
        <el-menu-item index="/manager/ai-chat">
          <el-icon><ChatDotRound /></el-icon>
          <span>AI智能助手</span>
        </el-menu-item>
        <el-menu-item index="/manager/notifications">
          <el-icon><Bell /></el-icon>
          <span>消息通知</span>
        </el-menu-item>
        <el-menu-item index="/manager/lab-list" v-if="userStore.isStudent">
          <el-icon><OfficeBuilding /></el-icon>
          <span>实验室列表</span>
        </el-menu-item>
        <el-menu-item index="/manager/my-reservation" v-if="userStore.isStudent">
          <el-icon><Tickets /></el-icon>
          <span>我的预约</span>
        </el-menu-item>
        <el-menu-item index="/manager/lab" v-if="userStore.isAdmin">
          <el-icon><house /></el-icon>
          <span>实验室管理</span>
        </el-menu-item>
        <el-menu-item index="/manager/equipment" v-if="userStore.isAdmin">
          <el-icon><setting /></el-icon>
          <span>设备列表管理</span>
        </el-menu-item>
        <el-menu-item index="/manager/audit-reservation" v-if="userStore.isAdmin">
          <el-icon><Checked /></el-icon>
          <span>预约审核</span>
        </el-menu-item>
        <el-menu-item index="/manager/user" v-if="userStore.isAdmin">
          <el-icon><user /></el-icon>
          <span>用户管理</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <!-- 抽屉展开时的遮罩：点一下关掉。桌面端由 CSS 隐藏。 -->
    <div v-if="menuOpen" class="layout-mask" @click="menuOpen = false"></div>

    <el-container class="layout-body">
      <el-header class="layout-header">
        <!-- 窄屏才出现的菜单按钮。用 CSS 控制显隐、不用 JS 判断屏宽：
             JS 判断要监听 resize，窗口一缩一放容易和 CSS 打架。 -->
        <button class="layout-burger" type="button" aria-label="打开菜单" @click="menuOpen = true">
          <el-icon><Fold /></el-icon>
        </button>

        <!-- 页头只留当前页名。原来这里是系统全名 + 用户，而系统名已经在左侧栏
             顶部了，同一屏出现两遍没有意义。 -->
        <div class="layout-title">{{ pageTitle }}</div>

        <div class="layout-header-right">
          <!-- 铃铛：未读数每 30 秒拉一次。消息本身不靠轮询，点开时才取最近 5 条，
               避免每个页面都多带一份列表数据。 -->
          <el-popover
            v-model:visible="noticeVisible"
            placement="bottom-end"
            :width="320"
            trigger="click"
            @show="loadRecent"
          >
            <template #reference>
              <button
                type="button"
                class="layout-notice"
                aria-label="消息通知"
                @click="loadUnreadCount"
              >
                <el-badge :value="unreadCount" :hidden="unreadCount === 0" :max="99">
                  <el-icon><Bell /></el-icon>
                </el-badge>
              </button>
            </template>

            <div class="notice-panel" v-loading="noticeLoading">
              <div class="notice-panel-head">
                <span class="notice-panel-title">消息通知</span>
                <el-button
                  link
                  type="primary"
                  size="small"
                  :disabled="unreadCount === 0"
                  @click="readAll"
                  >全部已读</el-button
                >
              </div>

              <div v-if="recentList.length" class="notice-panel-list">
                <div
                  v-for="item in recentList"
                  :key="item.id"
                  class="notice-panel-item"
                  :class="{ 'is-unread': !item.is_read }"
                  @click="openNotification(item)"
                >
                  <div class="notice-panel-item-title">
                    <span v-if="!item.is_read" class="notice-unread-dot"></span>
                    {{ item.title }}
                  </div>
                  <div class="notice-panel-item-content">{{ item.content }}</div>
                  <div class="notice-panel-item-time">
                    {{ formatNoticeTime(item.create_time) }}
                  </div>
                </div>
              </div>
              <el-empty v-else description="暂无消息" :image-size="52" />

              <div class="notice-panel-foot">
                <el-button link type="primary" size="small" @click="goNotifications">
                  查看全部消息
                </el-button>
              </div>
            </div>
          </el-popover>

          <el-dropdown @command="handleCommand">
            <div class="layout-user">
              <!-- 没上传过头像时必须有个兜底。原来是直接 <img :src="avatar">，
                   而 avatar 常常是空的 —— 空的 img 渲染不出任何东西，
                   窄屏下又正好把旁边的用户名藏了，于是"个人信息/修改密码/退出登录"
                   的入口整个变成隐形按钮。用姓名首字画个圆。 -->
              <img
                v-if="userStore.userInfo?.avatar"
                :src="userStore.userInfo.avatar"
                alt=""
                class="layout-avatar"
              />
              <span v-else class="layout-avatar layout-avatar-fallback">{{ userInitial }}</span>
              <div class="layout-user-text">
                <span class="layout-user-name">{{ userStore.userInfo?.name }}</span>
                <span class="layout-user-role">{{ userStore.roleLabel }}</span>
              </div>
              <el-icon class="layout-user-arrow"><ArrowDown /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile">个人信息</el-dropdown-item>
                <el-dropdown-item command="password">修改密码</el-dropdown-item>
                <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="layout-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import router from '@/router'
import { useUserStore } from '@/stores/user'
import { logoutApi } from '@/api/auth'
import {
  getNotificationPageListApi,
  getUnreadCountApi,
  markAllNotificationsReadApi,
  markNotificationReadApi
} from '@/api/notification'
import {
  Menu as IconMenu,
  Setting,
  User,
  House,
  OfficeBuilding,
  Tickets,
  Checked,
  ChatDotRound,
  Fold,
  ArrowDown,
  Bell
} from '@element-plus/icons-vue'

// 不要解构：const { userInfo } = useUserStore() 会丢掉响应性，
// 退出登录后页头头像和菜单就不会跟着更新了。统一走 userStore.xxx。
const userStore = useUserStore()

// 窄屏抽屉的开合状态。桌面端这个值一直是 false，由 CSS 保证侧栏始终可见，
// 所以不用管"桌面端误开抽屉"——那种情况下 CSS 里的样式根本不会生效。
const menuOpen = ref(false)

// ---------------------------------------------------------------------------
// 消息通知
// ---------------------------------------------------------------------------
const unreadCount = ref(0)
const noticeVisible = ref(false)
const recentList = ref([])
const noticeLoading = ref(false)
let unreadTimer = null

const loadUnreadCount = async () => {
  try {
    const res = await getUnreadCountApi()
    if (res.code === 200) unreadCount.value = res.data?.count || 0
  } catch {
    // 铃铛只是提示，拉不到就算了，30 秒后会再试，不弹错误打扰用户。
  }
}

const loadRecent = async () => {
  noticeLoading.value = true
  try {
    const res = await getNotificationPageListApi({ page: 1, page_size: 5 })
    if (res.code === 200) recentList.value = res.data.list || []
  } finally {
    noticeLoading.value = false
  }
}

const openNotification = async (item) => {
  if (!item.is_read) {
    try {
      const res = await markNotificationReadApi(item.id)
      if (res.code === 200) {
        item.is_read = true
        unreadCount.value = Math.max(0, unreadCount.value - 1)
      }
    } catch {
      // 标记失败不该挡住跳转：消息内容用户已经看到了。
    }
  }
  noticeVisible.value = false
  router.push(
    userStore.isAdmin ? '/manager/audit-reservation' : '/manager/my-reservation'
  )
}

const readAll = async () => {
  const res = await markAllNotificationsReadApi()
  if (res.code === 200) {
    unreadCount.value = 0
    recentList.value = recentList.value.map((item) => ({ ...item, is_read: true }))
    ElMessage.success(
      res.data?.count ? `已标记 ${res.data.count} 条为已读` : '没有未读消息'
    )
  }
}

const goNotifications = () => {
  noticeVisible.value = false
  router.push('/manager/notifications')
}

// 铃铛里空间小，只显示 MM-DD HH:mm。
const formatNoticeTime = (value) => {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(5, 16)
}

onMounted(() => {
  loadUnreadCount()
  unreadTimer = window.setInterval(loadUnreadCount, 30000)
})

onUnmounted(() => {
  if (unreadTimer) window.clearInterval(unreadTimer)
})

// 页头标题。写在组件里而不是加到路由 meta：这份表只有页头一个人用，
// 放进 router 反而让路由表多承担一个纯展示的职责。
const PAGE_TITLES = {
  '/manager/home': '系统首页',
  '/manager/ai-chat': 'AI 智能助手',
  '/manager/notifications': '消息通知',
  '/manager/lab-list': '实验室列表',
  '/manager/lab-equipment': '实验室设备',
  '/manager/my-reservation': '我的预约',
  '/manager/lab': '实验室管理',
  '/manager/equipment': '设备列表管理',
  '/manager/audit-reservation': '预约审核',
  '/manager/user': '用户管理',
  '/manager/profile': '个人信息',
  '/manager/password': '修改密码',
  '/manager/403': '无权访问'
}
const pageTitle = computed(() => PAGE_TITLES[router.currentRoute.value.path] || '')

// 没上传头像时的兜底：用姓名首字。跟聊天页 AIChat.vue 里那条保持一致。
const userInitial = computed(() => (userStore.userInfo?.name || '我').slice(0, 1))

// 点完菜单就收起抽屉。桌面端这么设也无害：侧栏本来就不会被这个状态影响。
const onMenuSelect = () => {
  menuOpen.value = false
}

const handleCommand = async (command) => {
  if (command === 'profile') {
    router.push('/manager/profile')
  } else if (command === 'password') {
    router.push('/manager/password')
  } else if (command === 'logout') {
    // 先通知后端把令牌版本 +1，再清本地。
    // 顺序不能反：清了 localStorage 之后请求就带不上令牌，后端不认是谁，
    // 那枚令牌会一直活到过期为止——正是这次要修的洞。
    // 请求失败（比如断网、令牌本来就过期）也必须继续清本地，否则用户被困在页面里。
    try {
      await logoutApi()
    } catch {
      // 拦截器已经提示过了，这里不重复弹
    }
    // 走 store 的 logout：它除了清 localStorage，还会把内存里的 userInfo 一起清掉。
    userStore.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.layout-root {
  min-height: 100vh;
  background-color: var(--app-bg-page);
}

/* ---------------------------------------------------------------------------
 * 侧栏
 * ------------------------------------------------------------------------- */
.layout-aside {
  display: flex;
  flex-direction: column;
  overflow-x: hidden;
  background-color: var(--app-sidebar-bg);
}

.layout-brand {
  flex: none;
  display: flex;
  align-items: center;
  gap: 10px;
  height: var(--app-header-height);
  padding: 0 18px;
  border-bottom: 1px solid var(--app-sidebar-divider);
}

.layout-logo {
  flex: 0 0 auto;
  width: 34px;
  height: 34px;
  border-radius: 9px;
}

.layout-brand-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.3;
}

.layout-brand-name {
  font-size: 15px;
  font-weight: 600;
  color: #fff;
  letter-spacing: 0.5px;
  white-space: nowrap;
}

.layout-brand-sub {
  font-size: 11px;
  color: #64748b;
  letter-spacing: 1.5px;
  white-space: nowrap;
}

/* 菜单本身透明，颜色全部由下面的规则给。
   EP 的 el-menu 会自己铺白底并画一条右边框，这两处都必须清掉。 */
.layout-menu {
  flex: 1;
  padding: 12px 0;
  border-right: none;
  background: transparent;
}

.layout-menu :deep(.el-menu-item) {
  height: 44px;
  line-height: 44px;
  margin: 2px 12px;
  padding: 0 12px !important;
  border-radius: 8px;
  font-size: 14px;
  color: var(--app-sidebar-text);
  transition:
    background-color 0.2s,
    color 0.2s;
}

.layout-menu :deep(.el-menu-item .el-icon) {
  margin-right: 10px;
  font-size: 17px;
  color: #7c8aa0;
  transition: color 0.2s;
}

.layout-menu :deep(.el-menu-item:hover) {
  background-color: var(--app-sidebar-bg-hover);
  color: #e2e8f0;
}

.layout-menu :deep(.el-menu-item:hover .el-icon) {
  color: #cbd5e1;
}

/* 选中项：淡主色底 + 左侧一道主色竖条 + 白字。
   原来是一整块高饱和的蓝色渐变，在白卡片旁边显得很跳；
   改成"只提亮一点 + 一条竖条"，定位照样清楚，但不会抢内容区的注意力。 */
.layout-menu :deep(.el-menu-item.is-active) {
  background-color: rgba(37, 99, 235, 0.22);
  box-shadow: inset 3px 0 0 #3b82f6;
  color: #fff;
  font-weight: 600;
}

.layout-menu :deep(.el-menu-item.is-active .el-icon) {
  color: #fff;
}

/* ---------------------------------------------------------------------------
 * 右侧：页头 + 内容
 * ------------------------------------------------------------------------- */
.layout-body {
  min-width: 0; /* 少了它，表格会把整个右侧撑出横向滚动条 */
}

.layout-header {
  display: flex;
  align-items: center;
  gap: 12px;
  height: var(--app-header-height);
  padding: 0 24px;
  background-color: #fff;
  border-bottom: 1px solid var(--app-card-border);
  /* 内容滚很长时页头留在顶上。sticky 只在滚动容器里生效，
     这里正是 el-main 在滚，所以用得上。 */
  position: sticky;
  top: 0;
  z-index: 9;
}

.layout-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--app-text-primary);
}

.layout-header-right {
  display: flex;
  align-items: center;
  margin-left: auto;
}

/* ---------------------------------------------------------------------------
 * 消息铃铛
 * ------------------------------------------------------------------------- */
.layout-notice {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  margin-right: 6px;
  padding: 0;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: var(--app-text-secondary);
  cursor: pointer;
  transition:
    background-color 0.2s,
    color 0.2s;
}

.layout-notice:hover {
  background-color: var(--app-bg-page);
  color: var(--app-primary);
}

.layout-notice :deep(.el-icon) {
  font-size: 19px;
}

.notice-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--app-border);
}

.notice-panel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--app-text-primary);
}

.notice-panel-list {
  max-height: 360px;
  overflow-y: auto;
}

.notice-panel-item {
  padding: 12px 6px;
  border-bottom: 1px solid var(--app-border);
  cursor: pointer;
  transition: background-color 0.2s;
}

.notice-panel-item:hover {
  background-color: var(--app-bg-muted);
}

.notice-panel-item.is-unread {
  background-color: var(--el-color-primary-light-9);
}

.notice-panel-item-title {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 13px;
  font-weight: 600;
  color: var(--app-text-primary);
}

.notice-unread-dot {
  flex: none;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--app-primary);
}

.notice-panel-item-content {
  margin-top: 5px;
  display: -webkit-box;
  overflow: hidden;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  font-size: 12px;
  line-height: 1.6;
  color: var(--app-text-secondary);
  word-break: break-word;
}

.notice-panel-item-time {
  margin-top: 5px;
  font-size: 11px;
  color: var(--app-text-placeholder);
}

.notice-panel-foot {
  padding-top: 8px;
  text-align: center;
  border-top: 1px solid var(--app-border);
}

.layout-user {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 5px 10px 5px 5px;
  border-radius: 10px;
  cursor: pointer;
  transition: background-color 0.2s;
}

.layout-user:hover {
  background-color: var(--app-bg-page);
}

.layout-avatar {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  object-fit: cover;
}

/* 没头像时那个首字圆：img 靠宽高就撑开了，span 得显式给布局和居中 */
.layout-avatar-fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  font-size: 14px;
  color: #fff;
  background: linear-gradient(135deg, #2563eb, #60a5fa);
}

.layout-user-text {
  display: flex;
  flex-direction: column;
  line-height: 1.3;
}

.layout-user-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--app-text-primary);
  white-space: nowrap;
}

.layout-user-role {
  font-size: 12px;
  color: var(--app-text-secondary);
  white-space: nowrap;
}

.layout-user-arrow {
  font-size: 12px;
  color: var(--app-text-secondary);
}

.layout-main {
  padding: 20px 24px;
}

/* 菜单按钮只在窄屏出现（规则见下面的 @media），桌面端不能占位置 */
.layout-burger {
  display: none;
}

.layout-mask {
  display: none;
}

@media (max-width: 767px) {
  .layout-header {
    padding: 0 12px;
  }

  .layout-main {
    padding: 12px;
  }

  /* 窄屏下用户名和角色让位给标题，头像留着——头像本身就能点开菜单 */
  .layout-user-text,
  .layout-user-arrow {
    display: none;
  }

  .layout-title {
    font-size: 15px;
  }

  .layout-burger {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: 0 0 auto;
    width: 34px;
    height: 34px;
    margin-right: 2px;
    padding: 0;
    font-size: 20px;
    color: var(--app-text-primary);
    background: transparent;
    border: none;
    cursor: pointer;
  }

  /* 抽屉：脱离文档流浮在内容上，默认推到屏幕外，展开时滑回来 */
  .layout-aside {
    position: fixed;
    top: 0;
    bottom: 0;
    left: 0;
    z-index: 2001;
    overflow-y: auto;
    transform: translateX(-100%);
    transition: transform 0.25s ease;
    box-shadow: 4px 0 24px rgba(15, 23, 42, 0.35);
  }
  .layout-aside.is-open {
    transform: translateX(0);
  }

  .layout-mask {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 2000;
    background-color: rgba(15, 23, 42, 0.45);
  }
}
</style>
