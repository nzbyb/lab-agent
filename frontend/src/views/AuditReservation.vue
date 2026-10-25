<template>
  <div>
    <el-card>
      <template #header>
        <div class="app-card-title">
          <span>预约审核</span>
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
        <el-button type="primary" @click="handleSearch">查询</el-button>
      </div>
      <el-table :data="tableData" style="width: 100%" v-loading="loading">
        <el-table-column prop="lab_name" label="实验室" />
        <el-table-column label="预约类型">
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
        <el-table-column prop="date" label="日期" />
        <el-table-column label="预约时段">
          <template #default="{ row }"> {{ row.start_time }} - {{ row.end_time }} </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" />
        <el-table-column prop="user_name" label="预约人" />
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
        <el-table-column label="操作" width="260">
          <template #default="{ row }">
            <template v-if="row.status === 0">
              <el-button type="success" text bg @click="handleAudit(row, 1)">通过</el-button>
              <el-button type="danger" text bg @click="handleAudit(row, 2)">拒绝</el-button>
            </template>
            <!-- 待审核和已通过都能强制取消。已拒绝、已取消的没有可取消的东西。 -->
            <el-button
              v-if="row.status === 0 || row.status === 1"
              type="warning"
              text
              bg
              @click="openForceCancel(row)"
              >强制取消</el-button
            >
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

    <el-dialog v-model="cancelDialogVisible" title="强制取消预约" width="450px">
      <el-form label-width="80px" class="app-dialog-form">
        <el-form-item label="预约">
          <span class="cancel-target">
            {{ cancelTarget?.lab_name }} · {{ cancelTarget?.date }}
            {{ cancelTarget?.start_time }}-{{ cancelTarget?.end_time }}
            <template v-if="cancelTarget?.user_name">（{{ cancelTarget.user_name }}）</template>
          </span>
        </el-form-item>
        <el-form-item label="取消原因" required>
          <el-input
            v-model="cancelReason"
            type="textarea"
            :rows="3"
            maxlength="100"
            show-word-limit
            placeholder="请填写取消原因，用户会在预约记录里看到"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="cancelDialogVisible = false">取消</el-button>
        <el-button type="danger" :loading="cancelSubmitting" @click="submitForceCancel">
          确认取消
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>
<script setup>
import {
  getReservationPageListApi,
  auditReservationApi,
  forceCancelReservationApi
} from '@/api/reservation'
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
const params = reactive({
  page: 1,
  page_size: 10,
  status: 0
})
const total = ref(0)

// 强制取消弹窗的状态
const cancelDialogVisible = ref(false)
const cancelTarget = ref(null)
const cancelReason = ref('')
const cancelSubmitting = ref(false)

const load = async () => {
  loading.value = true
  try {
    const res = await getReservationPageListApi(params)
    if (res.code === 200) {
      tableData.value = res.data?.list
      total.value = res.data?.total
    }
  } finally {
    loading.value = false
  }
}

const handleAudit = (row, status) => {
  const action = status === 1 ? '通过' : '拒绝'
  ElMessageBox.confirm(`${action} [${row.user_name}] 的预约 ? `, `审核`, { type: 'warning' })
    .then(async () => {
      const res = await auditReservationApi(row.id, status)
      if (res.code === 200) {
        ElMessage.success(`审核${action}`)
        load()
      }
    })
    .catch((err) => {
      if (err !== 'cancel' && err !== 'close') console.error(err)
    })
}

const openForceCancel = (row) => {
  cancelTarget.value = row
  cancelReason.value = ''
  cancelDialogVisible.value = true
}

const submitForceCancel = async () => {
  const reason = cancelReason.value.trim()
  // 后端也会卡（schema 里至少 2 个字），这里先拦一次是为了不白跑一趟请求。
  if (reason.length < 2) {
    ElMessage.warning('请填写取消原因（至少 2 个字）')
    return
  }
  cancelSubmitting.value = true
  try {
    const res = await forceCancelReservationApi(cancelTarget.value.id, reason)
    if (res.code === 200) {
      ElMessage.success('预约已强制取消')
      cancelDialogVisible.value = false
      load()
    }
  } finally {
    cancelSubmitting.value = false
  }
}

const handleSearch = () => {
  params.page = 1
  load()
}

onMounted(() => {
  load()
})
</script>

<style scoped>
/* 弹窗里的预约信息可能较长，允许换行，别把 label 挤变形 */
.cancel-target {
  display: inline-block;
  line-height: 1.5;
  word-break: break-all;
}
</style>
