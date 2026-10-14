<template>
  <div>
    <el-card>
      <template #header>
        <div class="app-card-title">
          <span>用户管理</span>
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
        <el-table-column prop="username" label="账号" />
        <el-table-column prop="name" label="名称" />
        <el-table-column prop="avatar" label="头像">
          <template #default="{ row }">
            <div style="min-height: 50px">
              <img
                v-if="row.avatar"
                style="display: block; width: 50px; height: 50px; border-radius: 50%"
                :src="row.avatar"
                alt=""
              />
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="email" label="邮箱" />
        <el-table-column prop="phone" label="手机号" />
        <el-table-column prop="role" label="角色" width="100">
          <template #default="{ row }">
            {{ row.role === 'admin' ? '管理员' : '学生' }}
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : 'danger'">
              {{ row.status === 1 ? '正常' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="250">
          <template #default="{ row }">
            <el-button type="primary" text bg @click="handleEdit(row)">编辑</el-button>
            <el-button type="warning" text bg @click="handleResetPassword(row)">重置密码</el-button>
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
        <el-form-item label="账号" prop="username">
          <el-input :disabled="!!form.id" v-model="form.username" placeholder="请输入账号" />
        </el-form-item>
        <!-- 只在新增时显示。后端 schemas/user.py 的 UserUpdateRequest **没有** password 字段，
             编辑时填的密码会被 pydantic 静默丢掉 —— 界面上「改了密码、提示成功、其实没改」。
             改别人的密码请走表格里的「重置密码」按钮（下一段那个弹窗），
             改自己的走 /manager/password 页面。
             这里用 v-if 而不是 disabled：FormItem 卸载时会连带把 prop 从表单注销，
             编辑态就不会再触发下面那条 required 校验。 -->
        <el-form-item v-if="!form.id" label="密码" prop="password">
          <el-input
            type="password"
            show-password
            v-model="form.password"
            placeholder="请输入密码"
          />
        </el-form-item>
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入名称" />
        </el-form-item>
        <el-form-item label="角色" prop="role">
          <el-select v-model="form.role">
            <el-option label="学生" value="student"></el-option>
            <el-option label="管理员" value="admin"></el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="form.email" placeholder="请输入邮箱" />
        </el-form-item>
        <el-form-item label="手机号" prop="phone">
          <el-input v-model="form.phone" placeholder="请输入手机号" />
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

    <!-- 重置密码。跟上面那个「编辑」弹窗分开，是因为两者的服务端语义完全不同：
         编辑走 PUT /api/user/{id}，请求体里**没有** password 字段（填了也会被
         pydantic 静默丢掉）；重置走 PUT /api/user/{id}/password，是这个功能唯一
         的入口。混在一个弹窗里迟早会有人以为"编辑里填密码就能改"。
         不设「确认密码」：管理员本来就不是这个密码的使用者，输错了再重置一次即可
         （新增用户那个表单也只有单个密码框，保持一致）。 -->
    <!-- 名字一律用 pwd 前缀，别用 reset*：本文件里已经有一个 resetForm() 函数
         （重置「编辑」弹窗用的），重名会直接编译不过。 -->
    <el-dialog v-model="pwdVisible" title="重置密码" width="420">
      <el-form
        ref="pwdFormRef"
        :rules="pwdRules"
        :model="pwdForm"
        label-width="80px"
        class="app-dialog-form"
      >
        <el-form-item label="账号">
          <span>{{ pwdForm.username }}</span>
        </el-form-item>
        <el-form-item label="新密码" prop="newPassword">
          <el-input
            type="password"
            show-password
            v-model="pwdForm.newPassword"
            placeholder="请输入新密码"
          />
        </el-form-item>
        <el-alert type="warning" :closable="false" show-icon>
          重置后，该用户已登录的所有设备都会立刻退出，需要用新密码重新登录。
        </el-alert>
      </el-form>
      <template #footer>
        <el-button @click="pwdVisible = false">取消</el-button>
        <el-button type="primary" :loading="pwdLoading" @click="submitResetPassword">
          确定
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { Search, Plus } from '@element-plus/icons-vue'
import {
  createUserApi,
  deleteUserApi,
  getUserPageListApi,
  resetUserPasswordApi,
  updateUserApi
} from '@/api/user'
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
  username: '',
  // 必须显式声明。Vue 3 的 reactive 允许运行时新增键，所以以前 v-model 能写进去、"看起来"正常，
  // 但 resetForm() 的 Object.assign 里没有这个键 → 清不掉，上一次输的明文密码会留在框里。
  password: '',
  name: '',
  role: 'student',
  email: '',
  phone: '',
  avatar: '',
  status: 1
})
const formLoading = ref(false)

// 重置密码弹窗。跟编辑弹窗的各状态完全独立，别合并——两者的提交地址和
// 成功后要做的事都不一样（编辑要刷新表格，重置不用）。
// ⚠️ 变量名一律 pwd 前缀：本文件已有一个 resetForm() 函数，再声明一个同名变量
// 会直接把构建打挂（Identifier 'resetForm' has already been declared）。
const pwdVisible = ref(false)
const pwdLoading = ref(false)
const pwdFormRef = ref()
// 三个键都显式声明，理由同上面 form 里那段注释：Object.assign 清不掉的键，
// 会在下次打开弹窗时把上一个人输过的明文密码留在框里。
const pwdForm = reactive({
  userId: null,
  username: '',
  newPassword: ''
})

const pwdRules = {
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    // 下限跟后端 schemas/user.py 的 PASSWORD_MIN_LENGTH 对齐（那边是 3）。
    // 上限（72 字节）不在这儿算：前端要按 UTF-8 字节数数，一个汉字 3 字节，
    // 用 max 会按字符数卡、跟后端对不上，索性交给后端，超了是 422。
    { min: 3, message: '密码至少 3 位', trigger: 'blur' }
  ]
}

const rules = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 3, max: 10, message: '密码是3-10位', trigger: 'blur' }
  ],
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  email: [{ type: 'email', message: '邮箱格式错误', trigger: 'blur' }],
  phone: [{ pattern: /^1[3-9]\d{9}$/, message: '手机号格式错误', trigger: 'blur' }]
}

const resetForm = () => {
  Object.assign(form, {
    id: null,
    username: '',
    password: '',
    name: '',
    role: 'student',
    email: '',
    phone: '',
    avatar: '',
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
    username: row.username,
    name: row.name,
    role: row.role,
    email: row.email,
    phone: row.phone,
    avatar: row.avatar,
    status: row.status
  })
  dialogVisible.value = true
}

const handleDelete = (row) => {
  ElMessageBox.confirm(`确认删除用户[${row.username}] ?`, `确认删除`, { type: 'warning' }).then(
    async () => {
      const res = await deleteUserApi(row.id)
      if (res.code === 200) {
        ElMessage.success('删除用户成功')
        load()
      }
    }
  )
}

const handleResetPassword = (row) => {
  pwdForm.userId = row.id
  pwdForm.username = row.username
  pwdForm.newPassword = ''
  // 上一次校验留下的红字要清掉，否则新打开的弹窗一上来就带着别人的报错。
  // 首次打开时 el-dialog 的内容还没渲染，拿不到 ref，所以要有 ?.
  pwdFormRef.value?.clearValidate()
  pwdVisible.value = true
}

const submitResetPassword = async () => {
  const valid = await pwdFormRef.value.validate().catch(() => false)
  if (!valid) return
  pwdLoading.value = true
  try {
    const res = await resetUserPasswordApi(pwdForm.userId, {
      new_password: pwdForm.newPassword
    })
    if (res.code === 200) {
      pwdVisible.value = false
      // 成功文案要带上"被踢下线"这件事：管理员点完就走了，不会去想对方的
      // 手机为什么突然退出登录，这条提示是唯一的交代。
      ElMessage.success(`已重置【${pwdForm.username}】的密码，该用户所有设备已退出登录`)
    }
  } finally {
    pwdLoading.value = false
  }
}

const handleSave = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  formLoading.value = true
  try {
    const res = form.id ? await updateUserApi(form.id, form) : await createUserApi(form)
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
    const res = await getUserPageListApi({
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

const handleSearch = async () => {
  params.page = 1
  load()
}

onMounted(() => {
  load()
})
</script>
