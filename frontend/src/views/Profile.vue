<template>
  <div class="settings-page">
    <el-card class="settings-card">
      <template #header>
        <div class="app-card-title">
          <span>个人信息</span>
        </div>
      </template>
      <el-form
        ref="formRef"
        :rules="rules"
        :model="form"
        label-width="80px"
        class="settings-form"
        v-loading="loading"
      >
        <el-form-item label="头像">
          <el-upload
            class="avatar-uploader"
            :http-request="handleFileUpload"
            :show-file-list="false"
            accept="image/jpeg,image/png,image/gif,image/webp"
            :before-upload="beforeAvatarUpload"
          >
            <img v-if="form.avatar" :src="form.avatar" class="avatar" />
            <el-icon v-else class="avatar-uploader-icon"><Plus /></el-icon>
          </el-upload>
        </el-form-item>
        <el-form-item label="账号">
          <el-input disabled v-model="form.username" placeholder="请输入账号" />
        </el-form-item>
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入名称" />
        </el-form-item>
        <el-form-item label="角色">
          <el-input disabled v-model="roleLabel" />
        </el-form-item>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="form.email" placeholder="请输入邮箱" />
        </el-form-item>
        <el-form-item label="手机号" prop="phone">
          <el-input v-model="form.phone" placeholder="请输入手机号" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="submitting" @click="handleSubmit">保存修改</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, computed } from 'vue'
import { uploadFileApi } from '@/api/file'
import { ElMessage } from 'element-plus'
import { getUserInfoApi, updateUserInfoApi } from '@/api/user'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()

const loading = ref(false)
const submitting = ref(false)
const formRef = ref()
const form = reactive({
  username: '',
  name: '',
  role: '',
  email: '',
  phone: '',
  avatar: ''
})

const rules = {
  name: [{ required: true, message: '请输入名称', trigger: 'blur' }],
  email: [{ type: 'email', message: '邮箱格式错误', trigger: 'blur' }],
  phone: [{ pattern: /^1[3-9]\d{9}$/, message: '手机号格式错误', trigger: 'blur' }]
}

const roleLabel = computed(() => {
  return form.role === 'admin' ? '管理员' : form.role === 'student' ? '学生' : '未知角色'
})

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
      form.avatar = res.data?.url
    }
  } catch {}
}

const loadUserInfo = async () => {
  loading.value = true
  try {
    const res = await getUserInfoApi()
    if (res.code === 200) {
      Object.assign(form, res.data)
    }
  } finally {
    loading.value = false
  }
}

const handleSubmit = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    const res = await updateUserInfoApi(form)
    if (res.code === 200) {
      userStore.updateUser(res.data)
      ElMessage.success('更新成功')
    }
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  loadUserInfo()
})
</script>

<style scoped>
/* 卡片居中、限宽。
   原来是 width: 50% 贴着左边排的：屏幕一宽，右半边空一大块，看着像没加载完；
   而输入框却被拉到很长，填一个名字要横跨半个屏幕。
   限到 720px 之后两种毛病一起没了。 */
.settings-page {
  display: flex;
  flex-direction: column;
  /* 内容区可视高度 = 视口 - 页头 - 上下内边距（20 + 20）。
     给这块高度，下面的 margin: auto 才有"剩余空间"可以分。 */
  min-height: calc(100vh - var(--app-header-height) - 40px);
}

.settings-card {
  width: 100%;
  max-width: 720px;
  /* 横竖都居中。内容比可视区高时，auto 会退化成 0，卡片从顶部开始，
     不会被推到屏幕上面去（用 justify-content: center 就会）。 */
  margin: auto;
}

.settings-form {
  width: 100%;
}

/* 窄屏（断点跟 global.css 一致）。
   手机的左右内边距是 12，所以这里减 24；卡片撑满整个宽度，限宽交给 max-width。 */
@media (max-width: 767px) {
  .settings-page {
    min-height: calc(100vh - var(--app-header-height) - 24px);
  }
}
</style>
