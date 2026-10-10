<template>
  <el-result icon="info" title="404" sub-title="页面不存在，地址可能拼错了">
    <template #extra>
      <el-button type="primary" @click="router.push('/manager/home')">返回首页</el-button>
    </template>
  </el-result>
</template>

<script setup>
import router from '@/router'
</script>
