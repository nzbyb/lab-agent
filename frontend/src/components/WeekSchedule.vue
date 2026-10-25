<template>
  <div class="week-schedule">
    <div class="week-head">
      <div class="week-head-main">
        <span class="week-title">一周占用</span>
        <span v-if="rangeText" class="week-range">{{ rangeText }}</span>
        <el-tag v-if="schedule?.equipment_name" size="small" type="info">
          {{ schedule.equipment_name }}
        </el-tag>
      </div>
      <el-button-group>
        <el-button size="small" :disabled="prevDisabled" @click="shiftWeek(-7)">
          上一周
        </el-button>
        <el-button size="small" :disabled="nextDisabled" @click="shiftWeek(7)">
          下一周
        </el-button>
      </el-button-group>
    </div>

    <div v-loading="loading" class="week-scroll">
      <div v-if="rows.length" class="week-grid">
        <div class="week-corner"></div>
        <div v-for="day in days" :key="day.date" class="week-day-head">
          <span class="week-day-name">{{ weekdayName(day.weekday) }}</span>
          <span class="week-day-date">{{ day.date.slice(5) }}</span>
        </div>

        <template v-for="row in rows" :key="row.start">
          <div class="week-time">{{ row.label }}</div>
          <button
            v-for="cell in row.cells"
            :key="`${cell.date}-${cell.start}`"
            type="button"
            class="week-cell"
            :class="`is-${cell.state}`"
            :disabled="cell.state !== 'free'"
            :title="cellTitle(cell)"
            @click="pick(cell)"
          >
            <span v-if="cell.state === 'free'">可约</span>
            <span v-else-if="cell.state === 'busy'">已约</span>
            <span v-else-if="cell.state === 'closed'">不开放</span>
            <span v-else>已过</span>
          </button>
        </template>
      </div>
      <el-empty v-else-if="!loading" description="这几天都没有开放时段" :image-size="64" />
    </div>

    <div class="week-legend">
      <span><i class="legend-dot is-free"></i>可预约</span>
      <span><i class="legend-dot is-busy"></i>已占用</span>
      <span><i class="legend-dot is-closed"></i>不开放</span>
      <span><i class="legend-dot is-past"></i>已过去</span>
      <span class="week-tip">点绿色格子自动填入日期和时间</span>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { getWeekScheduleApi } from '@/api/reservation'

const props = defineProps({
  labId: { type: Number, required: true },
  equipmentId: { type: Number, default: null }
})
const emit = defineEmits(['select'])

const WEEKDAY_NAMES = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
const SLOT_MINUTES = 60

const loading = ref(false)
const schedule = ref(null)
// null = 从今天开始；点「上一周/下一周」后变成具体的 YYYY-MM-DD。
const weekStart = ref(null)

const days = computed(() => schedule.value?.days || [])
const rangeText = computed(() => {
  if (!days.value.length) return ''
  return `${days.value[0].date} ~ ${days.value[days.value.length - 1].date}`
})

const toMinutes = (value) => {
  const [hour, minute] = String(value).split(':').map(Number)
  return hour * 60 + minute
}

const toLabel = (minutes) => {
  const hour = String(Math.floor(minutes / 60)).padStart(2, '0')
  const minute = String(minutes % 60).padStart(2, '0')
  return `${hour}:${minute}`
}

// 本地日期/时间。这里只和页面上的"已经过去"比较，不参与任何下单校验；
// 真正的"不能约过去"在后端 create_reservation 里。
const localDate = (value = new Date()) => {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

const nowMinutes = () => {
  const now = new Date()
  return now.getHours() * 60 + now.getMinutes()
}

const rows = computed(() => {
  if (!days.value.length) return []

  const openMinutes = []
  let maxEnd = 0
  for (const day of days.value) {
    if (!day.open_time || !day.close_time) continue
    openMinutes.push(toMinutes(day.open_time))
    maxEnd = Math.max(maxEnd, toMinutes(day.close_time))
  }
  if (!openMinutes.length) return []

  const startAt = Math.min(...openMinutes)
  const today = localDate()
  const currentMinutes = nowMinutes()
  const result = []

  for (let start = startAt; start < maxEnd; start += SLOT_MINUTES) {
    const end = start + SLOT_MINUTES
    const startText = toLabel(start)
    const endText = toLabel(end)
    const cells = days.value.map((day) => {
      let state = 'free'
      if (!day.open_time || !day.close_time) {
        // 当天不开放（比如周末），整列都是浅灰。
        state = 'closed'
      } else if (start < toMinutes(day.open_time) || end > toMinutes(day.close_time)) {
        // 这一小时没有被开放时段完整包住，不能单独约。
        state = 'closed'
      } else if (
        day.busy.some(
          (item) =>
            toMinutes(item.start_time) < end && toMinutes(item.end_time) > start
        )
      ) {
        state = 'busy'
      } else if (
        day.date < today ||
        (day.date === today && start < currentMinutes)
      ) {
        state = 'past'
      }
      return { date: day.date, start: startText, end: endText, state }
    })
    result.push({ start: startText, label: `${startText}-${endText}`, cells })
  }
  return result
})

const today = localDate()
const prevDisabled = computed(() => {
  const first = days.value[0]?.date
  return !first || first <= today
})
// 最多往后看一个月，避免一直点把请求打到很久以后。
const nextDisabled = computed(() => {
  const last = days.value[days.value.length - 1]?.date
  if (!last) return true
  const limit = new Date()
  limit.setDate(limit.getDate() + 30)
  return last >= localDate(limit)
})

const weekdayName = (weekday) => WEEKDAY_NAMES[weekday] || ''

const cellTitle = (cell) => {
  if (cell.state === 'free') return `${cell.date} ${cell.start}-${cell.end}，点击填入`
  if (cell.state === 'busy') return `${cell.date} ${cell.start}-${cell.end}，已被预约`
  if (cell.state === 'closed') return `${cell.date}，该时段不开放`
  return `${cell.date} ${cell.start}-${cell.end}，已经过去`
}

const load = async () => {
  if (!props.labId) return
  loading.value = true
  try {
    const params = { lab_id: props.labId }
    if (weekStart.value) params.week_start = weekStart.value
    if (props.equipmentId) params.equipment_id = props.equipmentId
    const res = await getWeekScheduleApi(params)
    if (res.code === 200) schedule.value = res.data
  } catch {
    // request.js 的拦截器已经弹过提示，这里不重复打扰。
  } finally {
    loading.value = false
  }
}

const shiftWeek = (offset) => {
  const base = days.value[0]?.date || today
  const date = new Date(`${base}T00:00:00`)
  date.setDate(date.getDate() + offset)
  weekStart.value = localDate(date)
  load()
}

const pick = (cell) => {
  if (cell.state !== 'free') return
  emit('select', {
    date: cell.date,
    start_time: cell.start,
    end_time: cell.end
  })
}

onMounted(load)
</script>

<style scoped>
.week-schedule {
  margin-bottom: 18px;
}

.week-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}

.week-head-main {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}

.week-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--app-text-primary);
}

.week-range {
  font-size: 12px;
  color: var(--app-text-secondary);
}

/* 7 列在窄屏挤不下时只让网格自己横向滚，不把整个弹窗撑宽 */
.week-scroll {
  overflow-x: auto;
  border: 1px solid var(--app-border);
  border-radius: 10px;
}

.week-grid {
  display: grid;
  grid-template-columns: 62px repeat(7, minmax(58px, 1fr));
  min-width: 540px;
  background: #fff;
}

.week-corner,
.week-day-head,
.week-time,
.week-cell {
  border-right: 1px solid var(--app-border);
  border-bottom: 1px solid var(--app-border);
}

.week-day-head {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 8px 4px;
  background: var(--app-bg-muted);
}

.week-day-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--app-text-primary);
}

.week-day-date {
  font-size: 11px;
  color: var(--app-text-secondary);
}

.week-time {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  color: var(--app-text-secondary);
  background: var(--app-bg-muted);
  white-space: nowrap;
}

.week-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 34px;
  padding: 0 2px;
  border-top: none;
  border-left: none;
  border-radius: 0;
  font-size: 11px;
  background: #fff;
  cursor: default;
}

.week-cell.is-free {
  color: #15803d;
  background: #ecfdf3;
  cursor: pointer;
  transition: background-color 0.15s;
}

.week-cell.is-free:hover {
  background: #d1fadf;
}

.week-cell.is-busy {
  color: #b91c1c;
  background: #fef2f2;
}

.week-cell.is-closed,
.week-cell.is-past {
  color: #b0b8c4;
  background: #f8fafc;
}

.week-cell:disabled {
  cursor: default;
}

.week-legend {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--app-text-secondary);
}

.week-legend span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.legend-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 3px;
}

.legend-dot.is-free {
  background: #b7f0c9;
}
.legend-dot.is-busy {
  background: #fecaca;
}
.legend-dot.is-closed {
  background: #e2e8f0;
}
.legend-dot.is-past {
  background: #eef2f7;
}

.week-tip {
  margin-left: auto;
  color: var(--app-text-placeholder);
}

@media (max-width: 767px) {
  .week-tip {
    margin-left: 0;
  }
}
</style>
