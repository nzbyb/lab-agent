<template>
  <div>
    <!-- 欢迎条。刻意不用渐变背景：渐变块占地很大却只承载"欢迎"这一件事，
         是典型的装饰性开销。改成白底 + 左侧一条主色竖条——同样的极简成本，
         但竖条是在表达"这里是页面起点"，有分区含义，不是纯装饰。 -->
    <div class="hero">
      <div class="hero-main">
        <div class="hero-title">{{ greeting }}，{{ userStore.userInfo?.name || '同学' }}</div>
        <div class="hero-sub">
          <span class="hero-tag">{{ userStore.roleLabel }}</span>
          <span>{{ todayText }}</span>
        </div>
      </div>
      <el-button type="primary" :icon="MagicStick" @click="router.push('/manager/ai-chat')">
        打开 AI 助手
      </el-button>
    </div>

    <!-- 四个指标磁贴。原来是"开放的实验室 10"和"预约数 16"两个裸数字并排一行，
         没有单位、没有口径、没有分母，看不出 10 是好还是不好。 -->
    <el-row :gutter="16" class="kpi-row">
      <el-col v-for="tile in kpiTiles" :key="tile.key" :xs="12" :sm="12" :md="6">
        <div class="kpi" :class="tile.tone ? `is-${tile.tone}` : ''">
          <div class="kpi-head">
            <span class="kpi-label">{{ tile.label }}</span>
            <el-icon class="kpi-icon"><component :is="tile.icon" /></el-icon>
          </div>
          <div class="kpi-value">
            {{ tile.value }}<span class="kpi-unit">{{ tile.unit }}</span>
          </div>
          <div class="kpi-foot">{{ tile.foot }}</div>
        </div>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <el-col :xs="24" :sm="24" :md="12">
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="panel-head">
              <div class="app-card-title">近 7 天预约趋势</div>
              <span class="panel-sub">共 {{ trendTotal }} 条</span>
            </div>
          </template>
          <!-- 全是 0 时不再画一张只有坐标轴的空图：7 根 0 高的柱子看起来就是"图坏了"，
               而一句"还没有新预约"把"没有数据"这件事说清楚了。 -->
          <BaseChart v-if="trendTotal > 0" :option="trendOption" height="260px" />
          <el-empty v-else description="近 7 天还没有新预约" :image-size="72" />
        </el-card>
      </el-col>

      <el-col :xs="24" :sm="24" :md="12">
        <el-card shadow="never" class="panel">
          <template #header>
            <div class="panel-head">
              <div class="app-card-title">实验室预约排行</div>
              <!-- 口径写在卡片头上：这个榜只算待审核和已通过，被拒/取消的不进榜。
                   不写出来，用户会拿它跟"预约总数"对不上而以为算错了。 -->
              <span class="panel-sub">仅待审核与已通过</span>
            </div>
          </template>
          <ul v-if="hasRanking" class="rank">
            <li v-for="(item, index) in rankingList" :key="item.lab_id" class="rank-item">
              <span class="rank-no" :class="{ 'is-top': index < 3 }">{{ index + 1 }}</span>
              <span class="rank-name" :title="item.lab_name">{{ item.lab_name }}</span>
              <span class="rank-track">
                <span class="rank-fill" :style="{ width: rankPercent(item.count) }"></span>
              </span>
              <span class="rank-count">{{ item.count }}</span>
            </li>
          </ul>
          <el-empty v-else description="暂无预约数据" :image-size="72" />
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" class="panel">
      <template #header>
        <div class="panel-head">
          <div class="app-card-title">预约状态分布</div>
          <span class="panel-sub">{{ userStore.reservationCountLabel }} {{ statusTotal }} 条</span>
        </div>
      </template>
      <template v-if="statusTotal > 0">
        <!-- 一条 100% 宽的横条，按比例分段。全 CSS，没有引入图表库：
             四段占比用一个 flex 容器加百分比宽度就够了，为它单开一个 echarts
             实例是杀鸡用牛刀，还要多担一份 resize 和 dispose。 -->
        <div class="seg">
          <div
            v-for="seg in statusSegments"
            :key="seg.key"
            class="seg-part"
            :class="`seg-${seg.key}`"
            :style="{ width: `${seg.percent}%` }"
            :title="`${seg.label} ${seg.count} 条`"
          ></div>
        </div>
        <ul class="legend">
          <li v-for="seg in statusSegments" :key="seg.key" class="legend-item">
            <span class="legend-dot" :class="`seg-${seg.key}`"></span>
            <span class="legend-label">{{ seg.label }}</span>
            <span class="legend-count">{{ seg.count }}</span>
            <span class="legend-percent">{{ seg.percentText }}</span>
          </li>
        </ul>
      </template>
      <el-empty v-else description="暂无预约记录" :image-size="72" />
    </el-card>

    <el-card shadow="never" class="panel">
      <template #header>
        <div class="panel-head">
          <div class="app-card-title">快捷入口</div>
        </div>
      </template>
      <!-- 原来是几个蓝色纯文字链接，32px 间距摊在一整张卡片的宽度上。
           文字链接的问题不是不好看，是"没有点击面积"——鼠标要从文字上精确划过
           才是手型光标。换成磁贴，整块都是热区。 -->
      <div class="shortcuts">
        <router-link v-for="item in shortcuts" :key="item.path" class="shortcut" :to="item.path">
          <el-icon class="shortcut-icon"><component :is="item.icon" /></el-icon>
          <span class="shortcut-label">{{ item.label }}</span>
          <el-icon class="shortcut-arrow"><ArrowRight /></el-icon>
        </router-link>
      </div>
    </el-card>

    <!-- 三张能力卡片。原来用 el-row/el-col :span="8" 写死三列，
         窄屏下三列会一起被压扁而不是换行；换成 CSS grid 的 auto-fit 自适应。 -->
    <div class="features">
      <div v-for="item in features" :key="item.title" class="feature">
        <div class="feature-head">
          <el-icon class="feature-icon"><component :is="item.icon" /></el-icon>
          <span class="feature-title">{{ item.title }}</span>
        </div>
        <div v-if="item.tag" class="feature-tag">{{ item.tag }}</div>
        <div class="feature-desc">{{ item.desc }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { getStatisticsOverviewApi } from '@/api/statistics'
import BaseChart from '@/components/BaseChart.vue'
import {
  ArrowRight,
  Calendar,
  Clock,
  Connection,
  Cpu,
  MagicStick,
  OfficeBuilding,
  Reading,
  Stamp,
  Tickets,
  User
} from '@element-plus/icons-vue'
import router from '@/router'
import { useUserStore } from '@/stores/user'

// 角色判据（isAdmin / isStudent）、角色中文名、以及那个随角色变含义的预约数文案，
// 都搬进了 stores/user.js——连同原来的注释一起，因为 Layout.vue 也要用同一套判据。
// 不要解构：const { userInfo } = useUserStore() 会丢掉响应性。
const userStore = useUserStore()

// 统计接口的原始返回。整页只发这一个请求。
const overview = ref(null)

// 拿不到数据时兜底 0，而不是让 undefined 显示到页面上。
const hasRanking = computed(() => rankingList.value.length > 0)
const rankingList = computed(() => overview.value?.lab_ranking || [])
const trendPoints = computed(() => overview.value?.reservation_trend || [])
const trendTotal = computed(() => trendPoints.value.reduce((sum, point) => sum + point.count, 0))

// ---------------------------------------------------------------------------
// 欢迎条上的问候语与日期
//
// 这两个 computed 没有任何响应式依赖，所以只会算一次、之后一直用缓存值。
// 也就是说它们是"页面打开那一刻"的快照：把页面挂着跨过 12 点，问候语不会自己变。
// 这是刻意的——为了一句问候语挂一个定时器，代价和收益不成比例。
// ---------------------------------------------------------------------------
const greeting = computed(() => {
  const hour = new Date().getHours()
  if (hour < 6) return '夜深了'
  if (hour < 11) return '早上好'
  if (hour < 14) return '中午好'
  if (hour < 18) return '下午好'
  return '晚上好'
})

const todayText = computed(() => {
  const now = new Date()
  // 不用 toLocaleDateString：它的输出随浏览器语言环境变，同一份代码在不同机器上
  // 会给出 "2026/10/11" 或 "10/11/2026"，排版会跟着跳。手拼格式才是稳定的。
  const week = ['日', '一', '二', '三', '四', '五', '六'][now.getDay()]
  return `${now.getFullYear()} 年 ${now.getMonth() + 1} 月 ${now.getDate()} 日 星期${week}`
})

// ---------------------------------------------------------------------------
// 四个指标磁贴
//
// 每个磁贴除了数字，还带一句"这个数字该怎么读"：分母、单位、或者要不要管。
// 只有一个孤立数字的时候，用户没法判断 0 是"很好"还是"坏了"。
// ---------------------------------------------------------------------------
const kpiTiles = computed(() => {
  const data = overview.value
  const labTotal = data?.lab_total ?? 0
  const labOpen = data?.lab_open_total ?? 0
  const equipmentTotal = data?.equipment_total ?? 0
  const equipmentNormal = data?.equipment_normal_total ?? 0
  const equipmentRepair = data?.equipment_repair_total ?? 0
  const pending = data?.reservation_pending_total ?? 0

  return [
    {
      key: 'lab',
      label: '开放实验室',
      icon: OfficeBuilding,
      value: labOpen,
      unit: '间',
      foot:
        labTotal > labOpen
          ? `共 ${labTotal} 间，${labTotal - labOpen} 间已关闭`
          : `共 ${labTotal} 间`
    },
    {
      key: 'equipment',
      label: '正常设备',
      icon: Cpu,
      value: equipmentNormal,
      unit: '台',
      foot: equipmentRepair > 0 ? `维修中 ${equipmentRepair} 台` : `共 ${equipmentTotal} 台`,
      // 有设备在修才标琥珀色。0 台维修时不标——那本来就是正常状态，
      // 给它上色等于把"一切正常"渲染成"有问题"。
      tone: equipmentRepair > 0 ? 'warning' : ''
    },
    {
      key: 'reservation',
      label: userStore.reservationCountLabel,
      icon: Calendar,
      value: data?.reservation_total ?? 0,
      unit: '条',
      // 和下面那张趋势图同源，两处数字天然一致
      foot: `近 7 天新增 ${trendTotal.value} 条`
    },
    {
      key: 'pending',
      label: '待审核',
      icon: Clock,
      value: pending,
      unit: '条',
      foot: userStore.isAdmin ? '等待你处理' : '等待管理员审核',
      tone: pending > 0 ? 'warning' : ''
    }
  ]
})

// ---------------------------------------------------------------------------
// 预约状态分布
// ---------------------------------------------------------------------------
const statusSegments = computed(() => {
  const data = overview.value
  // 顺序按流程排：待审核 → 已通过 / 已拒绝 → 已取消。
  // key 与后端字段的对应关系写在这里一处，模板只认 key。
  const items = [
    { key: 'pending', label: '待审核', count: data?.reservation_pending_total ?? 0 },
    { key: 'approved', label: '已通过', count: data?.reservation_approved_total ?? 0 },
    { key: 'rejected', label: '已拒绝', count: data?.reservation_rejected_total ?? 0 },
    { key: 'canceled', label: '已取消', count: data?.reservation_canceled_total ?? 0 }
  ]
  const total = items.reduce((sum, item) => sum + item.count, 0)
  return items.map((item) => {
    // total 为 0 时百分比必须是 0，不能是 NaN：0/0 会渲染成 width:NaN%，
    // 整条横条的宽度计算就废了。（空库时走的是 el-empty，这里只是双保险。）
    const percent = total > 0 ? (item.count / total) * 100 : 0
    return { ...item, percent, percentText: `${Math.round(percent)}%` }
  })
})
const statusTotal = computed(() =>
  statusSegments.value.reduce((sum, segment) => sum + segment.count, 0)
)

// ---------------------------------------------------------------------------
// 图表配色
//
// ECharts 画在 canvas 上，而 canvas 的 fillStyle 只认真实颜色字符串：把
// 'var(--app-primary)' 传进去**不会报错**，会被静默忽略并沿用上一个颜色。
// （实测 zrender 的颜色解析器 parse('var(--x)') 直接返回 undefined，确认它不解析
// CSS 变量；canvas 的绘制路径甚至根本没 import 那个 parse。）
// 结果就是图安静地画成错颜色——比抛异常更难发现。所以在运行时把变量取成实际色值。
// ---------------------------------------------------------------------------
const cssVar = (name, fallback) => {
  let value = ''
  try {
    value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  } catch {
    value = ''
  }
  // 取不到、或者拿回来仍是没解析的 var(...) 时一律回落到兜底色。
  // 绝不能把 'var(...)' 放行到 canvas 上——那正是上面说的静默错色。
  return !value || value.startsWith('var(') ? fallback : value
}

// option 用 computed 从 overview 派生：接口回来时自动重算，BaseChart 的 watch 收到新对象就重画。
const trendOption = computed(() => {
  const points = trendPoints.value
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    // containLabel 让坐标轴文字算进边距里，不然窄卡片上刻度会被裁掉
    grid: { left: 8, right: 16, top: 24, bottom: 4, containLabel: true },
    xAxis: {
      type: 'category',
      // 柱状图要留出半个格，柱子才落在刻度中间；boundaryGap:false 是折线图的写法，
      // 用在柱子上首尾两根会被卡片边缘切掉一半。
      boundaryGap: true,
      // 只留 MM-DD：7 个刻度下完整的 YYYY-MM-DD 会挤成一团
      data: points.map((point) => point.date.slice(5)),
      axisTick: { show: false },
      axisLine: { lineStyle: { color: cssVar('--app-border', '#e4e7ed') } },
      axisLabel: { color: cssVar('--app-text-secondary', '#909399') }
    },
    // 预约数是整数，minInterval: 1 免得出现 0.5 这种没有意义的刻度
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: cssVar('--app-grid-line', '#eef0f3') } },
      axisLabel: { color: cssVar('--app-text-secondary', '#909399') }
    },
    series: [
      {
        name: '新增预约',
        // 从折线+平滑+面积改成柱子：一天的预约数是个离散计数，
        // 平滑曲线会在两个相邻的日值之间画出中间态，7 个点看着像连续变化的量。
        type: 'bar',
        barMaxWidth: 32,
        itemStyle: {
          color: cssVar('--app-primary', '#409eff'),
          borderRadius: [4, 4, 0, 0]
        },
        data: points.map((point) => point.count)
      }
    ]
  }
})

// 排行条的宽度按**榜首**归一，而不是按总数：这样第一名永远是满格，
// 后面几名相对它的差距一眼可见。按总数归一的话，数据一多每根条都很短。
const rankMax = computed(() => Math.max(1, ...rankingList.value.map((item) => item.count)))
const rankPercent = (count) => `${Math.round((count / rankMax.value) * 100)}%`

const features = [
  {
    title: '业务预约',
    icon: Tickets,
    desc: '实验室 / 设备浏览、提交预约、我的预约和管理员审核'
  },
  {
    title: '知识库的问答',
    icon: Reading,
    desc: 'RAG 检索规则和开放时间等文档，回答有依据'
  },
  {
    title: '智能Agent',
    icon: Connection,
    // 这条标签是给"扫一眼"的人看的：这张卡片讲的是 Agent，
    // 具体用了什么技术写在正文里太长，抽成标签才可能被读到。
    tag: 'LangGraph · ReAct · Tool Calling',
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
      { label: '预约审核', path: '/manager/audit-reservation', icon: Stamp },
      { label: '实验室管理', path: '/manager/lab', icon: OfficeBuilding },
      { label: '设备列表管理', path: '/manager/equipment', icon: Cpu },
      { label: '用户管理', path: '/manager/user', icon: User }
    ]
  }
  return [
    { label: 'AI 智能助手', path: '/manager/ai-chat', icon: MagicStick },
    { label: '实验室列表', path: '/manager/lab-list', icon: OfficeBuilding },
    { label: '我的预约', path: '/manager/my-reservation', icon: Calendar }
  ]
})
onMounted(async () => {
  try {
    const res = await getStatisticsOverviewApi()
    if (res.code === 200) overview.value = res.data
  } catch {
    // 保持 null：模板里的 ?? 0 会把数字显示成 0，图表显示"暂无数据"。
    // 统计只是首页的锦上添花，不该因为它失败就弹错、或者让整页挂掉。
    overview.value = null
  }
})
</script>

<style scoped>
/* ---------------------------------------------------------------------------
 * 指标磁贴
 * ------------------------------------------------------------------------- */
/* 窄屏时 xs=12 会折成两行，行与行之间靠这个 margin 拉开 */
.kpi {
  height: 100%;
  margin-bottom: 16px;
  padding: 18px 20px;
  background: #fff;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
}
.kpi-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.kpi-label {
  font-size: 13px;
  color: var(--app-text-secondary);
}
.kpi-icon {
  font-size: 18px;
  color: var(--app-text-placeholder);
}
.kpi-value {
  margin-top: 10px;
  font-size: 28px;
  font-weight: 600;
  line-height: 1.2;
  color: var(--app-text-primary);
  /* 等宽数字：数字变化时宽度不跳动 */
  font-variant-numeric: tabular-nums;
}
.kpi-unit {
  margin-left: 4px;
  font-size: 13px;
  font-weight: 400;
  color: var(--app-text-secondary);
}
.kpi-foot {
  margin-top: 8px;
  font-size: 12px;
  color: var(--app-text-secondary);
}
.kpi.is-warning .kpi-value,
.kpi.is-warning .kpi-icon {
  color: var(--app-status-pending);
}

/* ---------------------------------------------------------------------------
 * 状态分布横条
 * ------------------------------------------------------------------------- */
.seg {
  display: flex;
  height: 14px;
  border-radius: 7px;
  overflow: hidden;
  /* 全 0 的段落宽度为 0，这里垫一个浅底，免得整条消失后看着像漏渲染 */
  background: var(--app-bg-muted);
}
.seg-part {
  height: 100%;
  transition: width 0.3s;
}
/* 相邻两段之间留一条白缝，否则同色系的两段会糊成一整块。
   全局 reset 里有 box-sizing: border-box，这条 1px 算在宽度内，不会撑破 100%。 */
.seg-part + .seg-part {
  border-left: 1px solid #fff;
}
/* 状态色一律走 global.css 里的语义变量，这里不抄色值。
   已取消用中性灰而不是红：取消是"失效"，不是"出错"。 */
.seg-pending {
  background: var(--app-status-pending);
}
.seg-approved {
  background: var(--app-status-approved);
}
.seg-rejected {
  background: var(--app-status-rejected);
}
.seg-canceled {
  background: var(--app-status-canceled);
}

/* 图例。auto-fit 让它在宽卡片上摊成 4 列、窄屏自动收到 2 列，不用写媒体查询。 */
.legend {
  margin-top: 18px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px 24px;
}
.legend-item {
  display: flex;
  align-items: center;
  font-size: 13px;
}
.legend-dot {
  flex: none;
  width: 8px;
  height: 8px;
  margin-right: 8px;
  border-radius: 2px;
}
.legend-label {
  color: var(--app-text-secondary);
}
.legend-count {
  margin-left: auto;
  font-weight: 600;
  color: var(--app-text-primary);
  font-variant-numeric: tabular-nums;
}
.legend-percent {
  width: 44px;
  margin-left: 6px;
  text-align: right;
  color: var(--app-text-secondary);
  font-variant-numeric: tabular-nums;
}

/* ---------------------------------------------------------------------------
 * 排行（横向榜，不再是竖柱状图）
 * ------------------------------------------------------------------------- */
.rank-item {
  display: flex;
  align-items: center;
  padding: 9px 0;
}
.rank-item + .rank-item {
  border-top: 1px solid var(--app-border);
}
.rank-no {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  margin-right: 12px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  background: var(--app-bg-muted);
  color: var(--app-text-secondary);
}
.rank-no.is-top {
  background: var(--el-color-primary-light-9);
  color: var(--app-primary);
}
.rank-name {
  flex: none;
  width: 150px;
  margin-right: 16px;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  color: var(--app-text-primary);
}
.rank-track {
  flex: 1;
  height: 8px;
  border-radius: 4px;
  overflow: hidden;
  background: var(--app-bg-muted);
}
.rank-fill {
  display: block;
  height: 100%;
  border-radius: 4px;
  background: var(--app-primary);
  transition: width 0.3s;
}
.rank-count {
  flex: none;
  width: 44px;
  margin-left: 16px;
  text-align: right;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

/* 窄屏下把名字列收窄，把宽度让给占比条 */
@media (max-width: 767px) {
  .rank-name {
    width: 92px;
    margin-right: 10px;
  }
  .rank-count {
    width: 34px;
    margin-left: 10px;
  }
}

/* ---------------------------------------------------------------------------
 * 卡片
 * ------------------------------------------------------------------------- */
.panel {
  margin-bottom: 16px;
}
/* 卡片头改成两端对齐：左边标题，右边补一句口径/汇总。
   baseline 对齐让 16px 的标题和 12px 的副标题坐在同一条基线上。 */
.panel-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}
.panel-sub {
  font-size: 12px;
  color: var(--app-text-secondary);
}
/* el-card 的默认圆角是 4px（--el-card-border-radius），跟上面那些 10px 的磁贴
   摆在同一屏里会明显不是一个体系。描边颜色不用动：--el-card-border-color 的默认值
   就是 --el-border-color-light，也就是 --app-border，本来就一致。
   作用域只在本页，其余 13 个页面维持原样。 */
.el-card {
  border-radius: var(--app-radius-lg);
}

/* ---------------------------------------------------------------------------
 * 欢迎条
 * ------------------------------------------------------------------------- */
.hero {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  padding: 18px 20px;
  background: #fff;
  border: 1px solid var(--app-border);
  /* 这条主色竖条代替渐变背景：同样的极简成本，但它在表达"页面起点"，
     是有含义的分区标记，而不是纯粹的装饰。 */
  border-left: 4px solid var(--app-primary);
  border-radius: var(--app-radius-lg);
}
.hero-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--app-text-primary);
}
.hero-sub {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
  font-size: 13px;
  color: var(--app-text-secondary);
}
.hero-tag {
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 12px;
  background: var(--el-color-primary-light-9);
  color: var(--app-primary);
}

/* ---------------------------------------------------------------------------
 * 快捷入口磁贴
 * ------------------------------------------------------------------------- */
/* auto-fit 让磁贴在宽屏摊开、窄屏自动换行，不必写媒体查询。
   原来这里是几个纯文字链接，问题不在好不好看，而在热区只有文字那么大。 */
.shortcuts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}
.shortcut {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  color: var(--app-text-primary);
  transition:
    border-color 0.2s,
    box-shadow 0.2s;
}
.shortcut:hover {
  border-color: var(--app-primary);
  box-shadow: var(--app-shadow-card);
}
.shortcut-icon {
  flex: none;
  font-size: 18px;
  color: var(--app-primary);
}
.shortcut-label {
  flex: 1;
  font-size: 14px;
}
.shortcut-arrow {
  flex: none;
  font-size: 12px;
  color: var(--app-text-placeholder);
}

/* ---------------------------------------------------------------------------
 * 能力卡片
 * ------------------------------------------------------------------------- */
/* 原来是 el-row + el-col :span="8" 写死三列，窄屏下三列会一起被压扁而不是换行 */
.features {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}
.feature {
  padding: 18px 20px;
  background: #fff;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
}
.feature-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.feature-icon {
  font-size: 18px;
  color: var(--app-primary);
}
.feature-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--app-text-primary);
}
.feature-tag {
  display: inline-block;
  margin-top: 10px;
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 12px;
  /* 技术标签用中性灰底而不是主色：它是注解，不该跟"可点击"的主色抢注意力 */
  background: var(--app-bg-muted);
  color: var(--app-text-secondary);
}
.feature-desc {
  margin-top: 10px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--app-text-secondary);
}
</style>
