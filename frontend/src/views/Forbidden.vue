<template>
  <el-result icon="warning" title="403" sub-title="当前账号没有访问这个页面的权限">
    <template #extra>
      <el-button type="primary" @click="router.push('/manager/home')">返回首页</el-button>
    </template>
  </el-result>
</template>

<script setup>
import router from '@/router'
</script>
