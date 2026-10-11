<template>
  <div>
    <el-card shadow="never" style="margin-bottom: 16px">
      <div style="display: flex; justify-content: space-between; align-items: center; gap: 16px">
        <div>
          <div style="font-size: 18px; color: #333">欢迎您: {{ userStore.userInfo?.name || '同学' }}</div>
          <div style="font-size: 14px; color: #999; margin-top: 8px">
            欢迎使用实验室预约系统，当前身份: {{ userStore.roleLabel }}
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
          {{ userStore.reservationCountLabel }}
          <b style="margin-left: 5px; font-size: 18px">{{ reservationCount }}</b>
        </div>
      </div>
    </el-card>

    <!-- 两张图同源（一次 /statistics/overview）。放在数字卡片之后、快捷入口之前。
         md 以上并排，窄屏堆叠：并排时图会被压到很窄，趋势的 7 个刻度会挤在一起。 -->
    <el-row :gutter="16">
      <el-col :xs="24" :sm="24" :md="12">
        <el-card shadow="never" style="margin-bottom: 16px">
          <template #header>
            <div class="app-card-title">近 7 天预约趋势</div>
          </template>
          <BaseChart :option="trendOption" />
        </el-card>
      </el-col>
      <el-col :xs="24" :sm="24" :md="12">
        <el-card shadow="never" style="margin-bottom: 16px">
          <template #header>
            <div class="app-card-title">实验室预约排行</div>
          </template>
          <!-- 一个实验室都没排上时，柱状图会是一张彻底空白的图，看着像坏了。
               换成明确的文案。（趋势图不用这样：空库时它是 7 个 0 的平线，本身就有信息量。） -->
          <BaseChart v-if="hasRanking" :option="rankingOption" />
          <el-empty v-else description="暂无预约数据" :image-size="80" />
        </el-card>
      </el-col>
    </el-row>

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
import { computed, onMounted, ref } from 'vue'
import { getStatisticsOverviewApi } from '@/api/statistics'
import BaseChart from '@/components/BaseChart.vue'
import router from '@/router'
import { useUserStore } from '@/stores/user'

// 角色判据（isAdmin / isStudent）、角色中文名、以及那个随角色变含义的预约数文案，
// 都搬进了 stores/user.js——连同原来的注释一起，因为 Layout.vue 也要用同一套判据。
// 不要解构：const { userInfo } = useUserStore() 会丢掉响应性。
const userStore = useUserStore()

// 统计接口的原始返回。整页只发这一个请求。
const overview = ref(null)

// 这两个数字以前是假的：拉两次分页接口（page_size: 1）只为了读 res.data.total，
// 后端根本没有统计能力。现在由 /api/statistics/overview 一次算好。
// 拿不到数据时兜底 0，而不是让 undefined 显示到页面上。
const openLabCount = computed(() => overview.value?.lab_open_total ?? 0)
const reservationCount = computed(() => overview.value?.reservation_total ?? 0)
const hasRanking = computed(() => (overview.value?.lab_ranking?.length || 0) > 0)

// option 用 computed 从 overview 派生：接口回来时自动重算，BaseChart 的 watch 收到新对象就重画。
const trendOption = computed(() => {
  const points = overview.value?.reservation_trend || []
  return {
    tooltip: { trigger: 'axis' },
    // containLabel 让坐标轴文字算进边距里，不然窄卡片上刻度会被裁掉
    grid: { left: 12, right: 20, top: 24, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      // 只留 MM-DD：7 个刻度下完整的 YYYY-MM-DD 会挤成一团
      data: points.map((point) => point.date.slice(5))
    },
    // 预约数是整数，minInterval: 1 免得出现 0.5 这种没有意义的刻度
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      {
        name: '新增预约',
        type: 'line',
        smooth: true,
        areaStyle: {},
        data: points.map((point) => point.count)
      }
    ]
  }
})

const rankingOption = computed(() => {
  const items = overview.value?.lab_ranking || []
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: 12, right: 20, top: 24, bottom: 8, containLabel: true },
    xAxis: { type: 'category', data: items.map((item) => item.lab_name) },
    yAxis: { type: 'value', minInterval: 1 },
    series: [
      { name: '预约数', type: 'bar', barMaxWidth: 48, data: items.map((item) => item.count) }
    ]
  }
})

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
  if (userStore.isAdmin) {
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
    const res = await getStatisticsOverviewApi()
    if (res.code === 200) overview.value = res.data
  } catch {
    // 保持 null：模板里的 ?? 0 会把数字显示成 0，排行显示"暂无数据"。
    // 统计只是首页的锦上添花，不该因为它失败就弹错、或者让整页挂掉。
    overview.value = null
  }
})
</script>
