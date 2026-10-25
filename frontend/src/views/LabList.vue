<template>
  <div class="lab-page">
    <!-- 工具条：搜索和按钮排成一行，数量放最右边。
         原来整页套在一张大卡片里，搜索框、卡片网格、分页全挤在同一块白底上，
         看不出哪一层是"操作"、哪一层是"结果"。 -->
    <div class="lab-toolbar">
      <div class="toolbar-group">
        <el-input
          v-model="params.keywords"
          placeholder="搜索实验室名称或位置"
          class="toolbar-search"
          clearable
          :prefix-icon="Search"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
        <el-button type="primary" @click="handleSearch">查询</el-button>
        <el-button @click="handleReset">重置</el-button>
      </div>
      <span class="toolbar-count">共 {{ total }} 间实验室</span>
    </div>

    <div v-loading="loading" class="lab-grid">
      <el-card
        v-for="item in tableData"
        :key="item.id"
        shadow="never"
        class="lab-card"
        :body-style="{ padding: '0' }"
      >
        <div class="lab-cover">
          <img v-if="item.img" :src="item.img" alt="" class="lab-img" />
          <div v-else class="lab-img lab-img-empty">
            <el-icon><OfficeBuilding /></el-icon>
          </div>
          <!-- 状态分四态：已停用 / 今日不开放 / 开放中 / 已闭馆。
               全部由后端算好（status / today_open_time / open_now），
               前端不自己拿当前时间比时段，理由见 utils/lab.js。 -->
          <span class="lab-state" :class="`is-${labOpenState(item).type}`">
            <span class="lab-state-dot"></span>{{ labOpenState(item).text }}
          </span>
        </div>

        <div class="lab-body">
          <h3 class="lab-name" :title="item.name">{{ item.name }}</h3>
          <div class="lab-meta">
            <div class="lab-meta-item">
              <el-icon><Location /></el-icon>
              <span>{{ item.location || '未填写位置' }}</span>
            </div>
            <div class="lab-meta-item">
              <el-icon><User /></el-icon>
              <span>可容纳 {{ item.capacity }} 人</span>
            </div>
            <div class="lab-meta-item">
              <el-icon><Clock /></el-icon>
              <span>{{
                todayHoursText(item) ? `今日 ${todayHoursText(item)}` : '今日不开放'
              }}</span>
            </div>
          </div>
          <div class="lab-actions">
            <el-button @click="handleViewEquipment(item)">查看设备</el-button>
            <el-button type="primary" :disabled="item.status !== 1" @click="handleReserve(item)"
              >预约</el-button
            >
          </div>
        </div>
      </el-card>

      <el-empty
        v-if="!loading && tableData.length === 0"
        class="lab-empty"
        description="没有找到符合条件的实验室"
      />
    </div>

    <div v-if="total > 0" class="app-pagination">
      <el-pagination
        v-model:current-page="params.page"
        v-model:page-size="params.page_size"
        :total="total"
        background
        layout="prev, pager, next, total"
        @current-change="load"
      />
    </div>

    <reserve-dialog
      v-model:visible="reserveVisible"
      :lab-id="currentLab?.id"
      :lab-name="currentLab?.name"
    ></reserve-dialog>
  </div>
</template>
<script setup>
import { ref, reactive, onMounted } from 'vue'
import { getLab, getLabPageListApi } from '@/api/lab'
import { Search, Location, User, Clock, OfficeBuilding } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import router from '@/router'
import ReserveDialog from '@/components/ReserveDialog.vue'
import { labOpenState, todayHoursText } from '@/utils/lab'

const reserveVisible = ref(false)
const currentLab = ref(null)
const params = reactive({
  page: 1,
  page_size: 10,
  keywords: ''
})
const loading = ref(false)
const tableData = ref([])
const total = ref(0)

const handleViewEquipment = (lab) => {
  router.push({ path: '/manager/lab-equipment', query: { lab_id: lab.id } })
}

// 打开弹窗前重新确认一次实验室状态。
// 列表数据是挂载/搜索/翻页时拉的快照，用户停留本页期间管理员把实验室关掉时，
// 按钮上的 :disabled 读到的仍是旧值 1、照样放行——又回到「填完才被后端拒掉」。
// 这里补一次实时校验，把窗口压到「这次 fetch 到用户点确定」之间的毫秒级；
// 最终把关的仍然是后端 create_reservation 里的 lab.status 判断。
const ensureLabOpen = async (lab) => {
  if (!lab?.id) return false
  let res = null
  try {
    res = await getLab(lab.id)
  } catch {
    return false // fail-closed：request.js 的拦截器已经提示过了
  }
  // code !== 200 时拦截器已弹 toast 且**不 reject**，这里只取数据，不再补第二条提示
  if (res?.code !== 200) return false
  if (res.data?.status !== 1) {
    ElMessage.warning('该实验室已停用，暂不可预约')
    return false
  }
  return true
}

const handleReserve = async (lab) => {
  if (!(await ensureLabOpen(lab))) return
  currentLab.value = lab
  reserveVisible.value = true
}

const load = async () => {
  loading.value = true
  try {
    const res = await getLabPageListApi(params)
    if (res.code === 200) {
      tableData.value = res.data?.list
      total.value = res.data?.total
    }
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  params.page = 1
  load()
}

const handleReset = () => {
  params.keywords = ''
  handleSearch()
}

onMounted(() => {
  load()
})
</script>

<style scoped>
/* ---------------------------------------------------------------------------
 * 工具条
 * ------------------------------------------------------------------------- */
.lab-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
  padding: 14px 20px;
  background: #fff;
  border: 1px solid var(--app-card-border);
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.toolbar-group {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.toolbar-search {
  width: 280px;
}

.toolbar-count {
  margin-left: auto;
  font-size: 13px;
  color: var(--app-text-secondary);
}

/* ---------------------------------------------------------------------------
 * 卡片网格
 *
 * 用 CSS grid 的 auto-fill 而不是 el-row/el-col：列宽和列数由容器自己算，
 * 不需要为每个断点写一档 span。窄屏下 260px 的最小值会把列数自然降到 1。
 * ------------------------------------------------------------------------- */
.lab-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
  min-height: 160px;
}

.lab-card {
  overflow: hidden;
  transition:
    box-shadow 0.2s,
    transform 0.2s;
}

.lab-card:hover {
  box-shadow: 0 10px 24px -14px rgba(15, 23, 42, 0.35);
  transform: translateY(-2px);
}

/* 封面固定 150px 高：卡片网格里高度不齐会显得很乱，图片本身多高都裁掉 */
.lab-cover {
  position: relative;
  height: 150px;
  overflow: hidden;
  background: #eef2f7;
}

.lab-img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.35s;
}

.lab-card:hover .lab-img {
  transform: scale(1.04);
}

.lab-img-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 34px;
  color: #c3ccd9;
  background: linear-gradient(135deg, #f1f5fa, #e6ecf5);
}

/* 状态胶囊压在封面左上角。背景给足不透明度，压在任何一张图上都读得清；
   再加毛玻璃是给深色照片留的余量，不支持 blur 的浏览器只是少一层虚化。 */
.lab-state {
  position: absolute;
  top: 10px;
  left: 10px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 500;
  color: #fff;
  backdrop-filter: blur(6px);
}

/* 文字和底都是彩色的，圆点跟着文字色会看不见，所以单独给白 */
.lab-state-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #fff;
}

.lab-state.is-success {
  background: rgba(22, 163, 74, 0.92);
}
.lab-state.is-warning {
  background: rgba(217, 119, 6, 0.92);
}
.lab-state.is-info {
  background: rgba(100, 116, 139, 0.9);
}

/* ---------------------------------------------------------------------------
 * 卡片正文
 * ------------------------------------------------------------------------- */
.lab-body {
  display: flex;
  flex-direction: column;
  padding: 14px 16px 16px;
}

.lab-name {
  font-size: 15px;
  font-weight: 600;
  line-height: 1.4;
  color: var(--app-text-primary);
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.lab-meta {
  display: flex;
  flex-direction: column;
  gap: 7px;
  margin-top: 10px;
}

.lab-meta-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--app-text-secondary);
  min-width: 0;
}

.lab-meta-item .el-icon {
  flex: none;
  font-size: 14px;
  color: var(--app-text-placeholder);
}

.lab-meta-item span {
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

/* 按钮沉到底部：三行信息高度不一致时，两个按钮仍然对齐在同一条线上 */
.lab-actions {
  display: flex;
  gap: 8px;
  margin-top: auto;
  padding-top: 16px;
}

.lab-actions .el-button {
  flex: 1;
  margin-left: 0;
}

.lab-empty {
  grid-column: 1 / -1;
  padding: 40px 0;
}

@media (max-width: 767px) {
  .lab-toolbar {
    padding: 12px 14px;
  }

  /* 窄屏下搜索框独占一行，两个按钮并排在下面；数量落在最后一行 */
  .toolbar-group {
    width: 100%;
  }
  .toolbar-search {
    width: 100%;
  }
  .toolbar-count {
    margin-left: 0;
    width: 100%;
  }
}
</style>
