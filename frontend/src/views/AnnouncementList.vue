<template>
  <div>
    <el-card>
      <template #header>
        <div class="panel-head">
          <div class="app-card-title">校园公告</div>
          <el-button v-if="userStore.isAdmin" type="primary" :icon="Plus" @click="openCreate">
            发布公告
          </el-button>
        </div>
      </template>

      <div class="app-search-bar">
        <el-input
          v-model="params.keyword"
          placeholder="搜索标题或正文"
          class="ann-search"
          clearable
          :prefix-icon="Search"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        />
        <el-button type="primary" @click="handleSearch">查询</el-button>
        <el-button @click="handleReset">重置</el-button>
      </div>

      <div v-loading="loading" class="ann-list">
        <article v-for="item in list" :key="item.id" class="ann-item">
          <div class="ann-head">
            <el-tag v-if="item.pinned" type="danger" size="small" effect="plain">置顶</el-tag>
            <h3 class="ann-title">{{ item.title }}</h3>
            <el-tag v-if="item.status !== 1" type="info" size="small">草稿</el-tag>
            <div class="ann-head-right">
              <span class="ann-meta">
                {{ item.publisher_name || '系统' }} · {{ formatTime(item.create_time) }}
              </span>
              <template v-if="userStore.isAdmin">
                <el-button link type="primary" size="small" @click="openEdit(item)">编辑</el-button>
                <el-button link type="danger" size="small" @click="remove(item)">删除</el-button>
              </template>
            </div>
          </div>
          <div class="ann-content">{{ item.content }}</div>
        </article>

        <el-empty v-if="!loading && list.length === 0" description="暂无公告" />
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

    <el-dialog
      v-model="dialogVisible"
      :title="editing ? '编辑公告' : '发布公告'"
      width="560px"
    >
      <el-form label-width="70px" class="app-dialog-form">
        <el-form-item label="标题" required>
          <el-input v-model="form.title" maxlength="100" show-word-limit />
        </el-form-item>
        <el-form-item label="正文" required>
          <el-input
            v-model="form.content"
            type="textarea"
            :rows="8"
            maxlength="5000"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="置顶">
          <el-switch v-model="form.pinned" />
          <span class="form-tip">置顶的公告会排在列表最前面</span>
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="form.status">
            <el-radio :value="1">立即发布</el-radio>
            <el-radio :value="0">存为草稿</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import {
  createAnnouncementApi,
  deleteAnnouncementApi,
  getAnnouncementPageListApi,
  updateAnnouncementApi
} from '@/api/announcement'

const userStore = useUserStore()

const loading = ref(false)
const list = ref([])
const total = ref(0)
const params = reactive({
  page: 1,
  page_size: 10,
  keyword: ''
})

const load = async () => {
  loading.value = true
  try {
    const res = await getAnnouncementPageListApi({
      ...params,
      // 管理员要看到草稿才能继续编辑；学生就算传了后端也会忽略
      include_draft: userStore.isAdmin || undefined
    })
    if (res.code === 200) {
      list.value = res.data?.list || []
      total.value = res.data?.total || 0
    }
  } finally {
    loading.value = false
  }
}

const formatTime = (value) => {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(0, 16)
}

const handleSearch = () => {
  params.page = 1
  load()
}

const handleReset = () => {
  params.keyword = ''
  handleSearch()
}

// 新建/编辑共用一套表单
const dialogVisible = ref(false)
const editing = ref(null)
const saving = ref(false)
const form = reactive({
  title: '',
  content: '',
  pinned: false,
  status: 1
})

const openCreate = () => {
  editing.value = null
  Object.assign(form, { title: '', content: '', pinned: false, status: 1 })
  dialogVisible.value = true
}

const openEdit = (item) => {
  editing.value = item
  Object.assign(form, {
    title: item.title,
    content: item.content,
    pinned: item.pinned,
    status: item.status
  })
  dialogVisible.value = true
}

const save = async () => {
  if (!form.title.trim()) {
    ElMessage.warning('请填写标题')
    return
  }
  if (!form.content.trim()) {
    ElMessage.warning('请填写正文')
    return
  }
  saving.value = true
  try {
    const payload = { ...form }
    const res = editing.value
      ? await updateAnnouncementApi(editing.value.id, payload)
      : await createAnnouncementApi(payload)
    if (res.code === 200) {
      ElMessage.success(editing.value ? '已保存' : '公告已发布')
      dialogVisible.value = false
      load()
    }
  } finally {
    saving.value = false
  }
}

const remove = (item) => {
  ElMessageBox.confirm(`确认删除公告「${item.title}」？`, '删除公告', { type: 'warning' })
    .then(async () => {
      const res = await deleteAnnouncementApi(item.id)
      if (res.code === 200) {
        ElMessage.success('已删除')
        load()
      }
    })
    .catch((err) => {
      if (err !== 'cancel' && err !== 'close') console.error(err)
    })
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

.ann-search {
  width: 280px;
}

.ann-list {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 120px;
}

.ann-item {
  padding: 16px 18px;
  border: 1px solid var(--app-card-border);
  border-radius: 10px;
}

.ann-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.ann-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--app-text-primary);
}

.ann-head-right {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}

.ann-meta {
  font-size: 12px;
  color: var(--app-text-secondary);
  white-space: nowrap;
}

/* 正文保留换行：公告多是分条写的，压成一行会很难读 */
.ann-content {
  margin-top: 10px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--app-text-primary);
  white-space: pre-wrap;
  word-break: break-word;
}

.form-tip {
  margin-left: 10px;
  font-size: 12px;
  color: var(--app-text-secondary);
}

@media (max-width: 767px) {
  .ann-search {
    width: 100%;
  }

  .ann-head-right {
    margin-left: 0;
    width: 100%;
  }
}
</style>
