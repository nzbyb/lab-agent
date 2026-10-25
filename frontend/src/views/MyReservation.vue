<template>
  <div>
    <el-card>
      <template #header>
        <div class="app-card-title">
          <span>我的预约记录</span>
        </div>
      </template>

      <div class="app-search-bar">
        <el-select
          placeholder="请选择状态"
          v-model="params.status"
          class="app-search-select"
          clearable
          @change="handleSearch"
          @clear="handleSearch"
        >
          <el-option :value="0" label="待审核" />
          <el-option :value="1" label="已通过" />
          <el-option :value="2" label="已拒绝" />
          <el-option :value="3" label="已取消" />
        </el-select>
        <!-- 日期区间按 reservation.date 过滤，和"预约日期"是同一列，
             不是提交时间。两端都可以单独留空。 -->
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          class="date-range"
          @change="handleSearch"
        />
        <el-button type="primary" @click="handleSearch">查询</el-button>
        <el-button @click="handleReset">重置</el-button>
      </div>

      <el-table :data="tableData" style="width: 100%" v-loading="loading">
        <el-table-column prop="lab_name" label="实验室" />
        <el-table-column label="预约类型" width="110">
          <template #default="{ row }">
            <el-tag :type="row.type === '实验室预约' ? 'success' : 'primary'">
              {{ row.type }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="设备">
          <template #default="{ row }">
            {{ row.equipment_name || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="date" label="日期" width="120" />
        <el-table-column label="预约时段" width="130">
          <template #default="{ row }"> {{ row.start_time }} - {{ row.end_time }} </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" show-overflow-tooltip />
        <el-table-column label="预约状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">
              {{ statusText(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="取消原因" width="160" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.cancel_reason || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button type="primary" text bg @click="openDetail(row)">详情</el-button>
            <el-button
              v-if="row.status === 0 || (row.status === 1 && row.can_cancel)"
              type="danger"
              text
              bg
              @click="handleCancel(row)"
              >取消</el-button
            >
            <!-- 已通过但进了开始前 2 小时：按钮留着但明确置灰，
                 比直接消失更好——用户会知道"本来能取消，是时间不够了"，
                 而不是以为系统坏了。 -->
            <el-tooltip
              v-else-if="row.status === 1"
              content="距开始不足 2 小时，不能自行取消，请联系管理员"
              placement="top"
            >
              <span class="cancel-disabled">
                <el-button type="info" text bg disabled>不可取消</el-button>
              </span>
            </el-tooltip>
          </template>
        </el-table-column>
      </el-table>

      <div class="app-pagination">
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

    <!-- 详情抽屉：把一条预约的来龙去脉按时间顺序摆出来。
         时间点全部来自后端（create_time / audit_time / cancel_time），
         前端不拿 update_time 猜，免得改个备注就让时间线漂了。 -->
    <el-drawer v-model="detailVisible" title="预约详情" size="min(420px, 100vw)">
      <div v-if="detailRow">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="实验室">
            {{ detailRow.lab_name }}
          </el-descriptions-item>
          <el-descriptions-item label="设备">
            {{ detailRow.equipment_name || '整间实验室' }}
          </el-descriptions-item>
          <el-descriptions-item label="预约日期">
            {{ detailRow.date }}
          </el-descriptions-item>
          <el-descriptions-item label="预约时段">
            {{ detailRow.start_time }} - {{ detailRow.end_time }}
          </el-descriptions-item>
          <el-descriptions-item label="当前状态">
            <el-tag :type="statusType(detailRow.status)">
              {{ statusText(detailRow.status) }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="备注">
            {{ detailRow.remark || '-' }}
          </el-descriptions-item>
        </el-descriptions>

        <div class="timeline-title">状态时间线</div>
        <el-timeline>
          <el-timeline-item :timestamp="formatTime(detailRow.create_time)" color="#2563eb">
            提交预约
          </el-timeline-item>

          <!-- 已拒绝：审核那一步就是终点 -->
          <el-timeline-item
            v-if="detailRow.status === 2 && detailRow.audit_time"
            :timestamp="formatTime(detailRow.audit_time)"
            color="#f56c6c"
          >
            管理员拒绝
          </el-timeline-item>

          <!-- 已通过 / 通过后被取消：审核通过这一步 -->
          <el-timeline-item
            v-else-if="detailRow.audit_time"
            :timestamp="formatTime(detailRow.audit_time)"
            color="#67c23a"
          >
            管理员通过
          </el-timeline-item>

          <!-- 还在等审核 -->
          <el-timeline-item
            v-else-if="detailRow.status === 0"
            timestamp="等待中"
            color="#e6a23c"
          >
            等待管理员审核
          </el-timeline-item>

          <el-timeline-item
            v-if="detailRow.cancel_time"
            :timestamp="formatTime(detailRow.cancel_time)"
            color="#909399"
          >
            预约已取消
            <div class="timeline-note">
              {{ detailRow.cancel_reason || '本人取消' }}
            </div>
          </el-timeline-item>
        </el-timeline>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { getReservationPageListApi, cancelReservationApi } from '@/api/reservation'
import { ref, reactive, onMounted } from 'vue'
import { ElMessageBox, ElMessage } from 'element-plus'

const statusType = (status) => {
  return (
    {
      0: 'warning',
      1: 'success',
      2: 'danger',
      3: 'info'
    }[status] || '-'
  )
}
const statusText = (status) => {
  return (
    {
      0: '待审核',
      1: '已通过',
      2: '已拒绝',
      3: '已取消'
    }[status] || '-'
  )
}

const loading = ref(false)
const tableData = ref([])
const dateRange = ref([])
const params = reactive({
  page: 1,
  page_size: 10,
  status: null
})
const total = ref(0)

const detailVisible = ref(false)
const detailRow = ref(null)

// 后端返回的是 ISO 格式（2026-10-25T09:00:00），时间线里只显示到分钟。
const formatTime = (value) => {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(0, 16)
}

const load = async () => {
  loading.value = true
  try {
    const [dateFrom, dateTo] = dateRange.value || []
    const res = await getReservationPageListApi({
      ...params,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined
    })
    if (res.code === 200) {
      tableData.value = res.data?.list
      total.value = res.data?.total
    }
  } finally {
    loading.value = false
  }
}

const openDetail = (row) => {
  detailRow.value = row
  detailVisible.value = true
}

const handleCancel = (row) => {
  const tip =
    row.status === 1
      ? `确认取消[${row.lab_name}] 的预约？已通过的预约取消后时段会重新开放。`
      : `确认取消[${row.lab_name}] 的预约 ? `
  ElMessageBox.confirm(tip, `确认取消`, { type: 'warning' })
    .then(async () => {
      const res = await cancelReservationApi(row.id)
      if (res.code === 200) {
        ElMessage.success('取消预约成功')
        load()
      }
    })
    .catch((err) => {
      if (err !== 'cancel' && err !== 'close') console.error(err)
    })
}

const handleSearch = () => {
  params.page = 1
  load()
}

const handleReset = () => {
  params.status = null
  dateRange.value = []
  params.page = 1
  load()
}

onMounted(() => {
  load()
})
</script>

<style scoped>
.date-range {
  width: 260px;
  margin-right: var(--app-space-sm);
}

.cancel-disabled {
  display: inline-block;
}

.timeline-title {
  margin: 24px 0 14px;
  font-size: 14px;
  font-weight: 600;
  color: var(--app-text-primary);
}

.timeline-note {
  margin-top: 4px;
  font-size: 13px;
  color: var(--app-text-secondary);
  line-height: 1.5;
}

@media (max-width: 767px) {
  .date-range {
    width: 100%;
    margin-right: 0;
  }
}
</style>
