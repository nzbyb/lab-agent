<template>
  <div>
    <el-card>
      <template #header>
        <div class="panel-head">
          <div class="app-card-title">我的收藏与浏览记录</div>
          <el-button @click="router.push('/manager/lab-list')">去实验室列表</el-button>
        </div>
      </template>

      <el-tabs v-model="activeTab">
        <el-tab-pane name="favorite">
          <template #label>
            <span>我的收藏（{{ favorites.length }}）</span>
          </template>
          <div v-loading="loading" class="fav-grid">
            <el-card
              v-for="lab in favorites"
              :key="lab.id"
              shadow="hover"
              class="fav-card"
            >
              <div class="fav-head">
                <span class="fav-name" :title="lab.name">{{ lab.name }}</span>
                <el-tag :type="labOpenState(lab).type" size="small">
                  {{ labOpenState(lab).text }}
                </el-tag>
              </div>
              <div class="fav-meta">
                <el-icon><Location /></el-icon>
                <span>{{ lab.location || '未填写位置' }}</span>
              </div>
              <div class="fav-meta">
                <el-icon><User /></el-icon>
                <span>可容纳 {{ lab.capacity }} 人</span>
              </div>
              <div class="fav-meta">
                <el-icon><Clock /></el-icon>
                <span>{{ todayHoursText(lab) ? `今日 ${todayHoursText(lab)}` : '今日不开放' }}</span>
              </div>
              <div class="fav-actions">
                <el-button size="small" @click="viewEquipment(lab)">查看设备</el-button>
                <el-button
                  size="small"
                  type="primary"
                  :disabled="lab.status !== 1"
                  @click="reserve(lab)"
                  >预约</el-button
                >
                <el-button size="small" type="danger" text bg @click="unfavorite(lab)">
                  取消收藏
                </el-button>
              </div>
            </el-card>
            <el-empty
              v-if="!loading && favorites.length === 0"
              class="fav-empty"
              description="还没有收藏的实验室，去实验室列表点右上角的星标吧"
            />
          </div>
        </el-tab-pane>

        <el-tab-pane label="最近浏览" name="recent">
          <div v-loading="loading" class="fav-grid">
            <el-card
              v-for="lab in recent"
              :key="lab.id"
              shadow="hover"
              class="fav-card"
            >
              <div class="fav-head">
                <span class="fav-name" :title="lab.name">{{ lab.name }}</span>
                <el-tag :type="labOpenState(lab).type" size="small">
                  {{ labOpenState(lab).text }}
                </el-tag>
              </div>
              <div class="fav-meta">
                <el-icon><Location /></el-icon>
                <span>{{ lab.location || '未填写位置' }}</span>
              </div>
              <div class="fav-meta">
                <el-icon><Clock /></el-icon>
                <span>{{ todayHoursText(lab) ? `今日 ${todayHoursText(lab)}` : '今日不开放' }}</span>
              </div>
              <div class="fav-actions">
                <el-button size="small" @click="viewEquipment(lab)">查看设备</el-button>
                <el-button
                  size="small"
                  type="primary"
                  :disabled="lab.status !== 1"
                  @click="reserve(lab)"
                  >预约</el-button
                >
              </div>
            </el-card>
            <el-empty
              v-if="!loading && recent.length === 0"
              class="fav-empty"
              description="还没有浏览记录"
            />
          </div>
        </el-tab-pane>
      </el-tabs>
    </el-card>

    <reserve-dialog
      v-model:visible="reserveVisible"
      :lab-id="currentLab?.id"
      :lab-name="currentLab?.name"
    ></reserve-dialog>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import router from '@/router'
import { Location, User, Clock } from '@element-plus/icons-vue'
import { getFavoriteListApi, getRecentViewsApi, removeFavoriteApi } from '@/api/favorite'
import ReserveDialog from '@/components/ReserveDialog.vue'
import { labOpenState, todayHoursText } from '@/utils/lab'

const activeTab = ref('favorite')
const loading = ref(false)
const favorites = ref([])
const recent = ref([])

const reserveVisible = ref(false)
const currentLab = ref(null)

const load = async () => {
  loading.value = true
  try {
    // 两块数据一起拉：总数最多几十条，省一次切换标签的等待
    const [favRes, recentRes] = await Promise.all([
      getFavoriteListApi(),
      getRecentViewsApi({ limit: 10 })
    ])
    if (favRes.code === 200) favorites.value = favRes.data || []
    if (recentRes.code === 200) recent.value = recentRes.data || []
  } finally {
    loading.value = false
  }
}

const unfavorite = async (lab) => {
  const res = await removeFavoriteApi(lab.id)
  if (res.code === 200) {
    ElMessage.success('已取消收藏')
    favorites.value = favorites.value.filter((item) => item.id !== lab.id)
  }
}

const viewEquipment = (lab) => {
  router.push({ path: '/manager/lab-equipment', query: { lab_id: lab.id } })
}

const reserve = (lab) => {
  currentLab.value = lab
  reserveVisible.value = true
}

onMounted(load)
</script>

<style scoped>
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.fav-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
  min-height: 160px;
}

.fav-card :deep(.el-card__body) {
  display: flex;
  flex-direction: column;
  gap: 8px;
  height: 100%;
}

.fav-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.fav-name {
  min-width: 0;
  overflow: hidden;
  font-size: 15px;
  font-weight: 600;
  white-space: nowrap;
  text-overflow: ellipsis;
  color: var(--app-text-primary);
}

.fav-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--app-text-secondary);
}

.fav-meta .el-icon {
  flex: none;
  color: var(--app-text-placeholder);
}

.fav-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: auto;
  padding-top: 10px;
}

.fav-empty {
  grid-column: 1 / -1;
  padding: 40px 0;
}
</style>
