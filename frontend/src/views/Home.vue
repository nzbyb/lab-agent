<template>
  <div>
    <el-card shadow="never" style="margin-bottom: 16px">
      <div style="display: flex; justify-content: space-between; align-items: center; gap: 16px">
        <div>
          <div style="font-size: 18px; color: #333">欢迎您: {{ userInfo?.name || '同学' }}</div>
          <div style="font-size: 14px; color: #999; margin-top: 8px">
            欢迎使用实验室预约系统，当前身份: {{ userInfo.role === 'student' ? '学生' : '管理员' }}
          </div>
        </div>
        <el-button type="primary" @click="router.push('/manager/ai-chat')">打开AI助手</el-button>
      </div>
    </el-card>

    <el-card shadow="never" style="margin-bottom: 16px">
      <div style="display: flex; align-items: center; gap: 50px">
        <div>
          开放的实验室 <b style="margin-left: 5px; font-size: 18px">{{ openLabCount }}</b>
        </div>
        <div>
          与我相关的预约 <b style="margin-left: 5px; font-size: 18px">{{ reservationCount }}</b>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" style="margin-bottom: 16px">
      <template #header>
        <div style="font-size: 16px">
          <span>快捷入口</span>
        </div>
      </template>
      <div style="display: flex; flex-wrap: wrap; gap: 32px">
        <router-link
          v-for="(item, index) in shortcuts"
          :key="index"
          style="color: #409eff"
          :to="item.path"
          >{{ item.label }}</router-link
        >
      </div>
    </el-card>

    <div style="margin-bottom: 16px">
      <el-row :gutter="16">
        <el-col :span="8" v-for="(item, index) in features" :key="index">
          <el-card shadow="never">
            <div style="padding: 10px">
              <div style="font-size: 16px; font-weight: 600; color: #333">{{ item.title }}</div>
              <div
                style="
                  margin-top: 8px;
                  color: #666;
                  font-size: 13px;
                  line-height: 1.6;
                  min-height: 40px;
                "
              >
                {{ item.desc }}
              </div>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { getLabPageListApi } from '@/api/lab'
import { getReservationPageListApi } from '@/api/reservation'
import router from '@/router'
import { useUser } from '@/utils/user'
import { onMounted } from 'vue'

const { userInfo } = useUser()
const openLabCount = ref(0)
const reservationCount = ref(0)

const features = [
  {
    title: '业务预约',
    desc: '实验室 / 设备浏览、提交预约、我的预约和管理员审核'
  },
  {
    title: '知识库的问答',
    desc: 'RAG 检索规则和开放时间等文档，回答有依据'
  },
  {
    title: '智能Agent',
    desc: '根据用户输入的自然语言主动进行 Tool Call 和 节点的编排循环调用， 可以查库、查空闲时段，流式对话， 确认表单提交'
  }
]

const shortcuts = computed(() => {
  if (userInfo.value.role === 'student') {
    return [
      { label: 'AI 智能助手', path: '/manager/ai-chat' },
      { label: '实验室列表', path: '/manager/lablist' },
      { label: '我的预约', path: '/manager/my-reservation' }
    ]
  }
  return [
    { label: '预约审核', path: '/manager/audit-reservation' },
    { label: '实验室管理', path: '/manager/lab' },
    { label: '设备列表管理', path: '/manager/equipment' },
    { label: '用户管理', path: '/manager/user' }
  ]
})
onMounted(async () => {
  try {
    const res = await getLabPageListApi({ page: 1, page_size: 1, status: 1 })
    if (res.code === 200) openLabCount.value = res.data?.total || 0
  } catch {
    openLabCount.value = 0
  }
  try {
    const res = await getReservationPageListApi({ page: 1, page_size: 1 })
    if (res.code === 200) reservationCount.value = res.data?.total || 0
  } catch {
    reservationCount.value = 0
  }
})
</script>
