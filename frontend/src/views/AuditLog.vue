<template>
  <div>
    <el-card>
      <template #header>
        <div class="app-card-title">操作日志与登录日志</div>
      </template>

      <div class="app-search-bar">
        <el-select
          v-model="params.category"
          placeholder="全部分类"
          class="log-category"
          clearable
          @change="handleSearch"
          @clear="handleSearch"
        >
          <el-option value="login" label="登录日志" />
          <el-option value="operation" label="操作日志" />
        </el-select>
        <el-input
          v-model="params.username"
          placeholder="操作人账号（支持模糊）"
          class="log-input"
          clearable
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
        <el-input
          v-model="params.action"
          placeholder="动作代码，如 login"
          class="log-input"
          clearable
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          class="log-date"
          @change="handleSearch"
        />
        <el-button type="primary" @click="handleSearch">查询</el-button>
        <el-button @click="handleReset">重置</el-button>
      </div>

      <el-table :data="tableData" style="width: 100%" v-loading="loading">
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ formatTime(row.create_time) }}</template>
        </el-table-column>
        <el-table-column label="分类" width="100">
          <template #default="{ row }">
            <el-tag :type="row.category === 'login' ? 'primary' : 'success'" size="small">
              {{ row.category === 'login' ? '登录' : '操作' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="动作" width="160">
          <template #default="{ row }">
            <div class="log-action">{{ actionText(row.action) }}</div>
            <div class="log-action-code">{{ row.action }}</div>
          </template>
        </el-table-column>
        <el-table-column label="操作人" width="140">
          <template #default="{ row }">
            {{ row.username || '-' }}
            <span v-if="!row.user_id" class="log-anon">（未匹配账号）</span>
          </template>
        </el-table-column>
        <el-table-column label="对象" width="140">
          <template #default="{ row }">
            {{ row.target_type ? `${targetTypeText(row.target_type)}#${row.target_id ?? '-'}` : '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="detail" label="说明" min-width="180" show-overflow-tooltip />
        <el-table-column prop="ip" label="IP" width="140" show-overflow-tooltip />
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
import { onMounted, reactive, ref } from 'vue'
import { getAuditLogPageListApi } from '@/api/audit'

// 动作代码 → 中文。代码本身也一起显示在下面一行：
// 排查问题时按代码搜更准，中文是给人看的。
const ACTION_TEXT = {
  'login.success': '登录成功',
  'login.failure': '登录失败',
  'login.logout': '退出登录',
  'user.register': '自助注册',
  'user.create': '新增用户',
  'user.update': '修改用户',
  'user.delete': '删除用户',
  'user.password_change': '修改密码',
  'user.password_reset': '找回密码',
  'user.password_reset_by_admin': '管理员重置密码',
  'lab.create': '新增实验室',
  'lab.update': '修改实验室',
  'lab.delete': '删除实验室',
  'equipment.create': '新增设备',
  'equipment.update': '修改设备',
  'equipment.delete': '删除设备',
  'reservation.approve': '通过预约',
  'reservation.reject': '驳回预约',
  'reservation.force_cancel': '强制取消预约',
  'announcement.create': '发布公告',
  'announcement.update': '修改公告',
  'announcement.delete': '删除公告',
  'statistics.export': '导出报表'
}

const TARGET_TYPE_TEXT = {
  user: '用户',
  lab: '实验室',
  equipment: '设备',
  reservation: '预约',
  announcement: '公告'
}

const loading = ref(false)
const tableData = ref([])
const total = ref(0)
const dateRange = ref([])
const params = reactive({
  page: 1,
  page_size: 20,
  category: null,
  username: '',
  action: ''
})

const actionText = (code) => ACTION_TEXT[code] || code
const targetTypeText = (type) => TARGET_TYPE_TEXT[type] || type

const formatTime = (value) => {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(0, 19)
}

const load = async () => {
  loading.value = true
  try {
    const [startDate, endDate] = dateRange.value || []
    const res = await getAuditLogPageListApi({
      ...params,
      start_date: startDate || undefined,
      end_date: endDate || undefined
    })
    if (res.code === 200) {
      tableData.value = res.data?.list || []
      total.value = res.data?.total || 0
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
  params.category = null
  params.username = ''
  params.action = ''
  dateRange.value = []
  handleSearch()
}

onMounted(load)
</script>

<style scoped>
.log-category {
  width: 130px;
}

.log-input {
  width: 180px;
}

.log-date {
  width: 240px;
}

.log-action {
  font-size: 13px;
  color: var(--app-text-primary);
}

.log-action-code {
  font-size: 11px;
  color: var(--app-text-placeholder);
}

.log-anon {
  font-size: 11px;
  color: var(--app-text-placeholder);
}

@media (max-width: 767px) {
  .log-category,
  .log-input,
  .log-date {
    width: 100%;
  }
}
</style>
