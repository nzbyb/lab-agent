<template>
  <div>
    <el-card>
      <template #header>
        <div class="notice-page-head">
          <div class="app-card-title">消息通知</div>
          <div class="notice-page-actions">
            <el-switch
              v-model="unreadOnly"
              active-text="只看未读"
              @change="handleFilter"
            />
            <el-button :disabled="unreadCount === 0" @click="markAllRead">
              全部标为已读
            </el-button>
          </div>
        </div>
      </template>

      <div v-loading="loading">
        <ul v-if="list.length" class="notice-page-list">
          <li
            v-for="item in list"
            :key="item.id"
            class="notice-page-item"
            :class="{ 'is-unread': !item.is_read }"
            @click="openItem(item)"
          >
            <span class="notice-page-dot" :class="{ 'is-visible': !item.is_read }"></span>
            <div class="notice-page-main">
              <div class="notice-page-title">
                {{ item.title }}
                <el-tag v-if="!item.is_read" size="small" type="primary">未读</el-tag>
              </div>
              <div class="notice-page-content">{{ item.content }}</div>
              <div class="notice-page-time">{{ formatTime(item.create_time) }}</div>
            </div>
            <el-icon class="notice-page-arrow"><ArrowRight /></el-icon>
          </li>
        </ul>
        <el-empty v-else description="暂时没有消息" :image-size="80" />
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
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowRight } from '@element-plus/icons-vue'
import router from '@/router'
import { useUserStore } from '@/stores/user'
import {
  getNotificationPageListApi,
  getUnreadCountApi,
  markAllNotificationsReadApi,
  markNotificationReadApi
} from '@/api/notification'

const userStore = useUserStore()

const loading = ref(false)
const list = ref([])
const total = ref(0)
const unreadCount = ref(0)
const unreadOnly = ref(false)
const params = reactive({ page: 1, page_size: 10 })

const load = async () => {
  loading.value = true
  try {
    const res = await getNotificationPageListApi({
      page: params.page,
      page_size: params.page_size,
      unread_only: unreadOnly.value
    })
    if (res.code === 200) {
      list.value = res.data.list || []
      total.value = res.data.total || 0
    }
    // 未读数单独取：列表只是当前这一页，拿这一页里未读的条数当总数，
    // 会出现"第 1 页全读完了、按钮变灰，但第 2 页还有未读"。
    const unreadRes = await getUnreadCountApi()
    if (unreadRes.code === 200) unreadCount.value = unreadRes.data?.count || 0
  } finally {
    loading.value = false
  }
}

const handleFilter = () => {
  params.page = 1
  load()
}

// 点一条消息：先标记已读（失败也不挡跳转，消息本身已经看到了），
// 再回到对应的预约页面。管理员去审核页，学生去我的预约。
const openItem = async (item) => {
  if (!item.is_read) {
    const res = await markNotificationReadApi(item.id)
    if (res.code === 200) {
      item.is_read = true
      unreadCount.value = Math.max(0, unreadCount.value - 1)
    }
  }
  router.push(
    userStore.isAdmin ? '/manager/audit-reservation' : '/manager/my-reservation'
  )
}

const markAllRead = async () => {
  const res = await markAllNotificationsReadApi()
  if (res.code === 200) {
    ElMessage.success(
      res.data?.count ? `已标记 ${res.data.count} 条为已读` : '没有未读消息'
    )
    unreadCount.value = 0
    load()
  }
}

// 后端返回的是 ISO 时间（2026-10-25T09:30:00），只留到分钟。
const formatTime = (value) => {
  if (!value) return '-'
  return String(value).replace('T', ' ').slice(0, 16)
}

onMounted(load)
</script>

<style scoped>
.notice-page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.notice-page-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}

.notice-page-list {
  margin: 0;
  padding: 0;
  list-style: none;
}

.notice-page-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 18px 8px;
  border-bottom: 1px solid var(--app-border);
  cursor: pointer;
  transition: background-color 0.2s;
}

.notice-page-item:hover {
  background-color: var(--app-bg-muted);
}

.notice-page-item:last-child {
  border-bottom: none;
}

.notice-page-dot {
  flex: none;
  width: 8px;
  height: 8px;
  margin-top: 7px;
  border-radius: 50%;
  background: transparent;
}

.notice-page-dot.is-visible {
  background: var(--app-primary);
}

.notice-page-main {
  flex: 1;
  min-width: 0;
}

.notice-page-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--app-text-primary);
}

.notice-page-content {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--app-text-secondary);
  word-break: break-word;
}

.notice-page-time {
  margin-top: 8px;
  font-size: 12px;
  color: var(--app-text-placeholder);
}

.notice-page-arrow {
  flex: none;
  margin-top: 4px;
  color: var(--app-text-placeholder);
}

/* 未读项左侧加一条主色竖条，扫一眼就知道哪些没看过 */
.notice-page-item.is-unread {
  box-shadow: inset 3px 0 0 var(--app-primary);
  background-color: var(--el-color-primary-light-9);
}

@media (max-width: 767px) {
  .notice-page-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .notice-page-actions {
    width: 100%;
    justify-content: space-between;
  }

  .notice-page-arrow {
    display: none;
  }
}
</style>
