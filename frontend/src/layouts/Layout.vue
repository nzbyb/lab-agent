<template>
  <div>
    <el-container style="min-height: 100vh">
      <el-header
        style="
          display: flex;
          align-items: center;
          border-bottom: 1px solid #ddd;
          background-color: #fff;
        "
      >
        <div
          style="flex: 1; display: flex; align-items: center; font-size: 24px; font-weight: bold"
        >
          <img src="@/assets/imgs/logo.jpg" alt="Logo" style="width: 80px" />
          <div style="margin-left: 5px">智能实验室预约系统</div>
        </div>
        <div>
          <el-dropdown @command="handleCommand">
            <div style="display: flex; align-items: center; cursor: pointer">
              <img :src="userStore.userInfo?.avatar" alt="" style="width: 40px; border-radius: 50%" />
              <div style="margin-left: 3px">{{ userStore.userInfo?.name }}</div>
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
      <el-container>
        <el-aside width="220px">
          <el-menu router :default-active="router.currentRoute.value.path" style="height: 100%">
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
        <el-main>
          <router-view />
        </el-main>
      </el-container>
    </el-container>
  </div>
</template>

<script setup>
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
  ChatDotRound
} from '@element-plus/icons-vue'

// 不要解构：const { userInfo } = useUserStore() 会丢掉响应性，
// 退出登录后页头头像和菜单就不会跟着更新了。统一走 userStore.xxx。
const userStore = useUserStore()

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
