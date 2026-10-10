<template>
  <div>
    <el-card shadow="never" style="margin-bottom: 16px">
      <div style="display: flex; justify-content: space-between; align-items: center; gap: 16px">
        <div>
          <div style="font-size: 18px; color: #333">欢迎您: {{ userInfo?.name || '同学' }}</div>
          <div style="font-size: 14px; color: #999; margin-top: 8px">
            欢迎使用实验室预约系统，当前身份: {{ roleLabel }}
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
          {{ reservationCountLabel }}
          <b style="margin-left: 5px; font-size: 18px">{{ reservationCount }}</b>
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

// 角色判据收敛到一处，一律精确匹配 admin，兜底落到最小权限侧。
// 不能写成「非 student 即管理员」：token 在而 userInfo 缺失时 role 是 undefined，
// 那样会把一个未知身份渲染成管理员视图、并给出四条管理入口（点进去被守卫拦到 403，
// 403 的「返回首页」又 push 回这张管理首页，来回往复）。
// 兜底方向与 Layout.vue（=== 'admin' 才显示管理菜单）、Profile.vue（显式回落「未知角色」）
// 以及后端 get_reservation_page_list 那句 `role != "admin"` 对齐。
const isAdmin = computed(() => userInfo.value?.role === 'admin')
const isStudent = computed(() => userInfo.value?.role === 'student')
const roleLabel = computed(() => {
  if (isAdmin.value) return '管理员'
  if (isStudent.value) return '学生'
  return '未知角色'
})

// 下面这个数字的含义是随角色变的：后端 get_reservation_page_list 只对**非 admin**
// 按 user_id 过滤，所以学生拿到的是"我的预约数"，管理员拿到的是"全库预约总数"。
// 文案必须跟着一起变，否则管理员会把全库总数当成自己的。判据刻意和后端那句
// `role != "admin"` 对齐，以后加新角色也不会错位。
const reservationCountLabel = computed(() =>
  userInfo.value?.role === 'admin' ? '全部预约' : '与我相关的预约'
)

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
  // 判据刻意和后端那句 `role != "admin"` 对齐：只有明确是 admin 才给管理入口，
  // 其余（学生，以及 token 在但 userInfo 缺失的未知身份）一律给最小权限侧入口。
  // 不能反过来写成「非 student 即管理员」——未知身份会看到四条管理入口，
  // 点进去被守卫拦到 403，403 的「返回首页」又回到这张首页，来回往复。
  if (isAdmin.value) {
    return [
      { label: '预约审核', path: '/manager/audit-reservation' },
      { label: '实验室管理', path: '/manager/lab' },
      { label: '设备列表管理', path: '/manager/equipment' },
      { label: '用户管理', path: '/manager/user' }
    ]
  }
  return [
    { label: 'AI 智能助手', path: '/manager/ai-chat' },
    { label: '实验室列表', path: '/manager/lab-list' },
    { label: '我的预约', path: '/manager/my-reservation' }
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
