<template>
  <el-container class="layout-root">
    <el-header class="layout-header">
      <!-- 窄屏才出现的菜单按钮。用 CSS 控制显隐、不用 JS 判断屏宽：
         JS 判断要监听 resize，窗口一缩一放容易和 CSS 打架。 -->
      <button class="layout-burger" type="button" aria-label="打开菜单" @click="menuOpen = true">
        <el-icon><Fold /></el-icon>
      </button>

      <div class="layout-brand">
        <img src="@/assets/imgs/logo.svg" alt="Logo" class="layout-logo" />
        <span class="layout-brand-text">智能实验室预约系统</span>
      </div>

      <el-dropdown @command="handleCommand">
        <div class="layout-user">
          <!-- 没上传过头像时必须有个兜底。原来是直接 <img :src="avatar">，
               而 avatar 常常是空的 —— 空的 img 渲染不出任何东西，
               窄屏下又正好把旁边的用户名藏了（见下面的 @media），
               于是"个人信息/修改密码/退出登录"的入口整个变成隐形按钮。
               用姓名首字画个圆，跟聊天页的头像兜底是同一个做法。 -->
          <img
            v-if="userStore.userInfo?.avatar"
            :src="userStore.userInfo.avatar"
            alt=""
            class="layout-avatar"
          />
          <span v-else class="layout-avatar layout-avatar-fallback">{{ userInitial }}</span>
          <span class="layout-user-name">{{ userStore.userInfo?.name }}</span>
        </div>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="profile">个人信息</el-dropdown-item>
            <el-dropdown-item command="password">修改密码</el-dropdown-item>
            <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </el-header>

    <el-container>
      <!-- 同一块 DOM 换形态：桌面端是左边固定的侧栏，窄屏下是从左侧滑出的抽屉。
           不做成两套菜单，是为了避免两份菜单项各自维护、加一项漏一边。 -->
      <el-aside class="layout-aside" :class="{ 'is-open': menuOpen }" width="220px">
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

      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed, ref } from 'vue'
import router from '@/router'
import { useUserStore } from '@/stores/user'
import {
  Document,
  Menu as IconMenu,
  Location,
  Setting,
  User,
  House,
  OfficeBuilding,
  Tickets,
  Checked,
  ChatDotRound,
  Fold
} from '@element-plus/icons-vue'

// 不要解构：const { userInfo } = useUserStore() 会丢掉响应性，
// 退出登录后页头头像和菜单就不会跟着更新了。统一走 userStore.xxx。
const userStore = useUserStore()

// 窄屏抽屉的开合状态。桌面端这个值一直是 false，由 CSS 保证侧栏始终可见，
// 所以不用管"桌面端误开抽屉"——那种情况下 CSS 里的样式根本不会生效。
const menuOpen = ref(false)

// 没上传头像时的兜底：用姓名首字。跟聊天页 AIChat.vue 里那条保持一致。
const userInitial = computed(() => (userStore.userInfo?.name || '我').slice(0, 1))

// 点完菜单就收起抽屉。桌面端这么设也无害：侧栏本来就不会被这个状态影响。
const onMenuSelect = () => {
  menuOpen.value = false
}

const handleCommand = (command) => {
  if (command === 'profile') {
    router.push('/manager/profile')
  } else if (command === 'password') {
    router.push('/manager/password')
  } else if (command === 'logout') {
    // 走 store 的 logout：它除了清 localStorage，还会把内存里的 userInfo 一起清掉。
    // 改造前这里调的是 utils/auth 的 logout，只清 localStorage，
    // 于是退出后要整页刷新菜单和头像才会消失。
    userStore.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.layout-header {
  display: flex;
  align-items: center;
  border-bottom: 1px solid #ddd;
  background-color: #fff;
}

.layout-brand {
  flex: 1;
  display: flex;
  align-items: center;
  min-width: 0; /* 少了它，长标题会把用户头像挤出屏幕 */
  font-size: 24px;
  font-weight: bold;
}

.layout-logo {
  width: 48px;
  height: 48px;
  flex: 0 0 auto;
}

.layout-brand-text {
  margin-left: 5px;
  /* 窄屏下宁可截断也不要折行——折行会把页头撑成两行高，
     浏览器的地址栏占掉的高度就更不够用了。 */
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.layout-avatar {
  width: 40px;
  border-radius: 50%;
}

/* 没头像时那个首字圆：img 靠 width 就撑开了，span 得显式给高度和居中 */
.layout-avatar-fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 40px;
  flex: 0 0 auto;
  font-size: 16px;
  color: #fff;
  background-color: var(--app-primary);
}

.layout-user {
  display: flex;
  align-items: center;
  cursor: pointer;
}

.layout-user-name {
  margin-left: 3px;
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
    padding: 0 10px;
  }

  /* 页头在窄屏下要同时塞下：菜单按钮 + 图标 + 标题 + 头像 */
  .layout-brand {
    font-size: 16px;
  }
  .layout-logo {
    width: 30px;
    height: 30px;
  }
  /* 用户名让位给标题，头像留着——头像本身就能点开菜单 */
  .layout-user-name {
    display: none;
  }

  .layout-burger {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: 0 0 auto;
    width: 34px;
    height: 34px;
    margin-right: 6px;
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
    background-color: #fff;
    overflow-y: auto;
    transform: translateX(-100%);
    transition: transform 0.25s ease;
    box-shadow: 2px 0 10px rgba(0, 0, 0, 0.18);
  }
  .layout-aside.is-open {
    transform: translateX(0);
  }

  .layout-mask {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 2000;
    background-color: rgba(0, 0, 0, 0.45);
  }
}
</style>
