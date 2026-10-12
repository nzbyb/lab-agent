<template>
  <el-result icon="info" title="404" sub-title="页面不存在，地址可能拼错了">
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

// 没有上一页时不给"返回上一页"：直接把拼错的地址粘进新标签页打开时，
// history 里没有前一条，点回去会跳出本站，剩下的只有"返回首页"是安全的。
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
