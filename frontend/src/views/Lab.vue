<template>
  <div>
    <el-card>
      <template #header>
        <div class="app-card-title">
          <span>实验室管理</span>
        </div>
      </template>
      <div class="app-search-bar">
        <el-input
          placeholder="请输入账号或名称查询"
          v-model="params.keywords"
          class="app-search-input"
          clearable
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        ></el-input>
        <el-button type="primary" :icon="Search" @click="handleSearch">查询</el-button>
        <el-button type="success" :icon="Plus" @click="handleCreate">新增</el-button>
      </div>
      <el-table :data="tableData" style="width: 100%" v-loading="loading">
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="description" label="简介" />
        <el-table-column prop="img" label="封面">
          <template #default="{ row }">
            <div style="min-height: 50px">
              <img
                v-if="row.img"
                style="display: block; width: 50px; height: 50px"
                :src="row.img"
                alt=""
              />
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="location" label="位置" />
        <el-table-column prop="capacity" label="容量" />
        <!-- 两套时段分行显示。合成一行写"08:00-20:00 / 09:00-17:00"看不出哪套是周中，
             而这正是管理员最需要一眼看清的东西：周末留空表示周末不开放。 -->
        <el-table-column label="开放时间" min-width="180">
          <template #default="{ row }">
            <div>周中：{{ weekdayHoursText(row) || '不开放' }}</div>
            <div>周末：{{ weekendHoursText(row) || '不开放' }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <!-- 这一列说的是"管理员启用了没"，不是"此刻开着没"。所以是
                 启用/停用，不写"开启/关闭"——后者会被读成"现在能去"。 -->
            <el-tag :type="row.status === 1 ? 'success' : 'danger'">
              {{ row.status === 1 ? '启用' : '停用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160">
          <template #default="{ row }">
            <el-button type="primary" text bg @click="handleEdit(row)">编辑</el-button>
            <el-button type="danger" text bg @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="app-pagination">
        <el-pagination
          v-model:current-page="params.page"
          v-model:page-size="params.pageSize"
          :total="total"
          background
          layout="prev, pager, next, total"
          @current-change="load"
        />
      </div>
    </el-card>
    <el-dialog v-model="dialogVisible" :title="form.id ? '编辑' : '新增'" width="450">
      <el-form
        ref="formRef"
        :rules="rules"
        :model="form"
        label-width="80px"
        class="app-dialog-form"
        v-loading="loading"
      >
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入名称" />
        </el-form-item>
        <el-form-item label="简介" prop="description">
          <el-input type="textarea" v-model="form.description" placeholder="请输入简介" />
        </el-form-item>
        <el-form-item label="封面">
          <el-upload
            class="avatar-uploader"
            :http-request="handleFileUpload"
            :show-file-list="false"
            accept="image/jpeg,image/png,image/gif,image/webp"
            :before-upload="beforeAvatarUpload"
          >
            <img v-if="form.img" :src="form.img" class="avatar" />
            <el-icon v-else class="avatar-uploader-icon"><Plus /></el-icon>
          </el-upload>
        </el-form-item>
        <el-form-item label="位置">
          <el-input type="textarea" v-model="form.location" placeholder="请输入位置" />
        </el-form-item>
        <el-form-item label="容量" prop="capacity">
          <el-input-number :min="1" v-model="form.capacity" placeholder="请输入容量" />
        </el-form-item>
        <!-- 周中一套、周末一套。周末两个都留空 = 周末不开放，
             这是允许的（大部分实验室周末都不开），所以这里不加 required。 -->
        <el-form-item label="周中开放" prop="close_time">
          <el-time-picker
            v-model="form.open_time"
            format="HH:mm"
            value-format="HH:mm"
            placeholder="开始时间"
            style="width: 140px; margin-right: 8px"
          />
          <el-time-picker
            v-model="form.close_time"
            format="HH:mm"
            value-format="HH:mm"
            placeholder="结束时间"
            style="width: 140px"
          />
        </el-form-item>
        <el-form-item label="周末开放" prop="weekend_close_time">
          <el-time-picker
            v-model="form.weekend_open_time"
            format="HH:mm"
            value-format="HH:mm"
            placeholder="不开放"
            style="width: 140px; margin-right: 8px"
          />
          <el-time-picker
            v-model="form.weekend_close_time"
            format="HH:mm"
            value-format="HH:mm"
            placeholder="不开放"
            style="width: 140px"
          />
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="form.status">
            <el-radio :value="1">正常</el-radio>
            <el-radio :value="0">禁用</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="formLoading" @click="handleSave">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { Search, Plus } from '@element-plus/icons-vue'
import { createLabApi, deleteLabApi, getLabPageListApi, updateLabApi } from '@/api/lab'
import { uploadFileApi } from '@/api/file'
import { weekdayHoursText, weekendHoursText } from '@/utils/lab'
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
const params = reactive({
  page: 1,
  pageSize: 10,
  keywords: ''
})
const loading = ref(false)
const tableData = ref([])
const total = ref(0)
const dialogVisible = ref(false)
const formRef = ref()
const form = reactive({
  name: '',
  description: '',
  img: '',
  location: '',
  capacity: 1,
  open_time: '',
  close_time: '',
  // 周末这两个为空 = 周末不开放。存的是空字符串而不是 null，理由见 handleSave。
  weekend_open_time: '',
  weekend_close_time: '',
  status: 1
})
const formLoading = ref(false)

// 两个时段各一条校验：要么都填、要么都留空；都填了则关门必须晚于开门。
// 原来这个表单一点校验都没有，能填成 18:00-08:00 这种，存进去之后这间实验室
// 就永远是"已闭馆"，而且从界面上看不出是哪里填错了。
//
// "只填一个"必须拦住：后端 resolve_open_hours 里判定是"任一端为空 = 当天不开放"，
// 所以只填开始时间等于什么都没填——管理员填了 09:00、点保存、表格里却显示"不开放"，
// 却没有任何地方告诉他为什么。留空是"不开放"的合法写法，前提是两个一起留空。
const hoursValidator = (openField, closeField, label) => (_rule, _value, callback) => {
  const open = form[openField]
  const close = form[closeField]
  if (!open && !close) return callback() // 都留空 = 不开放，合法
  if (!open || !close) {
    return callback(new Error(`${label}要两个都填，或者都留空（留空表示不开放）`))
  }
  if (close <= open) return callback(new Error(`${label}的关门时间必须晚于开门时间`))
  callback()
}

const rules = {
  name: [{ required: true, message: '请输入实验室名称', trigger: 'blur' }],
  capacity: [{ required: true, message: '请输入容量', trigger: 'blur' }],
  // 校验挂在后一个选择器上：它在组合里排最后，改完它才对整组做判断最顺。
  // 但两个字段任意一个变动都要重验（trigger 里同时监听 change）。
  close_time: [
    {
      validator: hoursValidator('open_time', 'close_time', '周中开放时间'),
      trigger: 'change'
    }
  ],
  weekend_close_time: [
    {
      validator: hoursValidator('weekend_open_time', 'weekend_close_time', '周末开放时间'),
      trigger: 'change'
    }
  ]
}

const resetForm = () => {
  Object.assign(form, {
    id: null,
    name: '',
    description: '',
    img: '',
    location: '',
    capacity: 20,
    open_time: '08:00',
    close_time: '18:00',
    // 新增默认周末不开放：多数实验室本就如此，想开的自己填。
    weekend_open_time: '',
    weekend_close_time: '',
    status: 1
  })
}

const handleCreate = () => {
  resetForm()
  dialogVisible.value = true
}

const handleEdit = (row) => {
  resetForm()
  Object.assign(form, {
    id: row.id,
    name: row.name,
    description: row.description,
    img: row.img,
    location: row.location,
    capacity: row.capacity,
    open_time: row.open_time,
    close_time: row.close_time,
    // 后端读出来的可能是 null（从没设过周末），而 el-time-picker 只认 ''。
    // 塞 null 进去选择器会显示成一串 0，看着像"设过了"。
    weekend_open_time: row.weekend_open_time || '',
    weekend_close_time: row.weekend_close_time || '',
    status: row.status
  })
  dialogVisible.value = true
}

const handleDelete = (row) => {
  ElMessageBox.confirm(`确认删除实验室[${row.name}] ?`, `确认删除`, { type: 'warning' }).then(
    async () => {
      const res = await deleteLabApi(row.id)
      if (res.code === 200) {
        ElMessage.success('删除成功')
        load()
      }
    }
  )
}

const handleSave = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  formLoading.value = true
  try {
    // 周末两个字段必须发空字符串，不能发 null。
    // 后端 update_lab 走的是 model_dump(exclude_none=True)，null 会被当成"这个字段没提"
    // 直接丢掉，于是"管理员把周末时段清空 → 改回不开放"这个动作会静默不生效：
    // 界面看着清空了，数据库里还是老值，刷新一下又冒出来。
    // el-time-picker 清空时给的正好是 null，所以这一步非做不可。
    const payload = {
      ...form,
      weekend_open_time: form.weekend_open_time || '',
      weekend_close_time: form.weekend_close_time || ''
    }
    const res = form.id ? await updateLabApi(form.id, payload) : await createLabApi(payload)
    if (res.code === 200) {
      dialogVisible.value = false
      ElMessage.success('操作成功')
      load()
    }
  } finally {
    formLoading.value = false
  }
}

const load = async () => {
  loading.value = true
  try {
    const res = await getLabPageListApi({
      page: params.page,
      page_size: params.pageSize,
      keywords: params.keywords
    })
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

const beforeAvatarUpload = (file) => {
  const imageTypes = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
  if (!imageTypes.includes(file.type)) {
    ElMessage.error('只能上传图片')
    return false
  }
  if (file.size / 1024 / 1024 > 2) {
    ElMessage.error('上传图片大小不能超过2M')
    return false
  }
  return true
}

const handleFileUpload = async ({ file }) => {
  try {
    const res = await uploadFileApi(file)
    if (res.code === 200) {
      form.img = res.data?.url
    }
  } catch {}
}

onMounted(() => {
  load()
})
</script>
