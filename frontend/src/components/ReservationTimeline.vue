<template>
  <div v-loading="loading" class="timeline-wrap">
    <el-timeline v-if="items.length">
      <el-timeline-item
        v-for="item in items"
        :key="item.key"
        :timestamp="item.timestamp"
        :color="item.color"
      >
        <div class="timeline-item-title">{{ item.title }}</div>
        <div v-if="item.meta" class="timeline-item-meta">{{ item.meta }}</div>
        <div v-if="item.note" class="timeline-item-note">{{ item.note }}</div>
      </el-timeline-item>
    </el-timeline>
    <el-empty v-else-if="!loading" description="暂无变更记录" :image-size="60" />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { getReservationLogsApi } from '@/api/reservation'

/**
 * 预约变更时间线。
 *
 * 数据来自后端 reservation_logs（每次状态变更一行，带操作人），而不是
 * 用 create_time / audit_time / cancel_time 反推：
 * "谁把它取消的"这种信息只存在于日志里，字段反推不出来。
 *
 * 迁移前的老预约没有日志行，这时退回用预约上的几个时间点拼一条，
 * 免得升级后老用户点开详情看到一片空白。
 */
const props = defineProps({
  reservationId: {
    type: Number,
    default: null
  },
  fallback: {
    type: Object,
    default: null
  }
})

const ACTION_TEXT = {
  create: '提交预约',
  approve: '审核通过',
  reject: '审核驳回',
  cancel: '本人取消',
  force_cancel: '管理员强制取消',
  auto_cancel: '超时自动取消'
}
const ACTION_COLOR = {
  create: '#2563eb',
  approve: '#67c23a',
  reject: '#f56c6c',
  cancel: '#909399',
  force_cancel: '#e6a23c',
  auto_cancel: '#909399'
}
const STATUS_TEXT = {
  0: '待审核',
  1: '已通过',
  2: '已拒绝',
  3: '已取消'
}

const loading = ref(false)
const logs = ref([])

const formatTime = (value) => {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(0, 16)
}

const load = async () => {
  if (!props.reservationId) {
    logs.value = []
    return
  }
  loading.value = true
  try {
    const res = await getReservationLogsApi(props.reservationId)
    logs.value = res.code === 200 ? res.data || [] : []
  } catch {
    // 拉不到就用下面的兜底时间线，不额外弹错打断用户看详情
    logs.value = []
  } finally {
    loading.value = false
  }
}

const derivedItems = computed(() => {
  const row = props.fallback
  if (!row) return []
  const result = [
    {
      key: 'derived-create',
      timestamp: formatTime(row.create_time),
      color: '#2563eb',
      title: '提交预约',
      meta: '',
      note: ''
    }
  ]
  if (row.status === 2 && row.audit_time) {
    result.push({
      key: 'derived-audit',
      timestamp: formatTime(row.audit_time),
      color: '#f56c6c',
      title: '管理员拒绝',
      meta: '',
      note: ''
    })
  } else if (row.audit_time) {
    result.push({
      key: 'derived-audit',
      timestamp: formatTime(row.audit_time),
      color: '#67c23a',
      title: '审核通过',
      meta: '',
      note: ''
    })
  } else if (row.status === 0) {
    result.push({
      key: 'derived-pending',
      timestamp: '等待中',
      color: '#e6a23c',
      title: '等待管理员审核',
      meta: '',
      note: ''
    })
  }
  if (row.cancel_time) {
    result.push({
      key: 'derived-cancel',
      timestamp: formatTime(row.cancel_time),
      color: '#909399',
      title: '预约已取消',
      meta: '',
      note: row.cancel_reason || '本人取消'
    })
  }
  return result
})

const items = computed(() => {
  if (!logs.value.length) return derivedItems.value
  return logs.value.map((log) => {
    const statusText =
      log.to_status === null || log.to_status === undefined
        ? ''
        : STATUS_TEXT[log.to_status] || ''
    return {
      key: `log-${log.id}`,
      timestamp: formatTime(log.create_time),
      color: ACTION_COLOR[log.action] || '#909399',
      title: ACTION_TEXT[log.action] || log.action,
      meta: [log.operator_name || '系统', statusText].filter(Boolean).join(' · '),
      note: log.reason || ''
    }
  })
})

watch(
  () => props.reservationId,
  () => load(),
  { immediate: true }
)

defineExpose({ reload: load })
</script>

<style scoped>
.timeline-wrap {
  min-height: 40px;
}

.timeline-item-title {
  font-size: 14px;
  color: var(--app-text-primary);
}

.timeline-item-meta {
  margin-top: 2px;
  font-size: 12px;
  color: var(--app-text-secondary);
}

.timeline-item-note {
  margin-top: 6px;
  font-size: 13px;
  line-height: 1.5;
  color: var(--app-text-secondary);
}
</style>
