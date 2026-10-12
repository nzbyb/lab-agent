<template>
  <el-result icon="warning" title="403" sub-title="当前账号没有访问这个页面的权限">
    <template #extra>
      <div class="actions">
        <el-button v-if="canGoBack" type="primary" @click="router.back()">返回上一页</el-button>
        <el-button :type="canGoBack ? 'default' : 'primary'" @click="goHome">返回首页</el-button>
      </div>
    </template>
  </el-result>
</template>

<script setup>
import router from '@/router'

// 用路由名跳，不写死路径：以后 /manager/home 换了地方，这里不用跟着改。
function goHome() {
  router.push({ name: 'Home' })
}

// 什么时候不给"返回上一页"：
//   1. 没有上一页——直接把地址粘进新标签页打开时 history 里没有前一条，点回去会跳出本站；
//   2. 上一页就是 403 自己——守卫会把人原样弹回来，看起来像按钮坏了。
const back = window.history.state?.back
const canGoBack = typeof back === 'string' && back !== router.currentRoute.value.path
</script>

<style scoped>
.actions {
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
  gap: 12px;
}
</style>
