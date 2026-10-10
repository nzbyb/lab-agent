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
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <template v-if="row.status === 0">
              <el-button type="success" text bg @click="handleAudit(row, 1)">通过</el-button>
              <el-button type="danger" text bg @click="handleAudit(row, 2)">拒绝</el-button>
            </template>
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
  </div>
</template>
<script setup>
import { getReservationPageListApi, auditReservationApi } from '@/api/reservation'
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

const handleSearch = () => {
  params.page = 1
  load()
}

onMounted(() => {
  load()
})
</script>
