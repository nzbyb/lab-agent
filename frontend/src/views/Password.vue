<template>
  <div style="width: 50%">
    <el-card>
      <template #header>
        <div class="app-card-title">
          <span>修改密码</span>
        </div>
      </template>
      <el-form
        ref="formRef"
        :rules="rules"
        :model="form"
        label-width="80px"
        style="width: 100%; padding-right: 50px"
      >
        <el-form-item label="原密码" prop="oldPassword">
          <el-input
            type="password"
            show-password
            v-model="form.oldPassword"
            placeholder="请输入原密码"
          />
        </el-form-item>
        <el-form-item label="新密码" prop="newPassword">
          <el-input
            type="password"
            show-password
            v-model="form.newPassword"
            placeholder="请输入新密码"
          />
        </el-form-item>
        <el-form-item label="确认密码" prop="confirmPassword">
          <el-input
            type="password"
            show-password
            v-model="form.confirmPassword"
            placeholder="请确认新密码"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="submitting" @click="handleSubmit">保存修改</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { updatePasswordApi } from '@/api/user'
import router from '@/router'
import { useUserStore } from '@/stores/user'
import { ElMessage } from 'element-plus'
import { ref, reactive } from 'vue'

// 这里**不能**用 @/utils/auth 的 logout——那个只清 localStorage，内存里的
// userInfo 原封不动，退出后侧边栏菜单和页头头像要整页刷新才会消失。
// store 的 logout 两个都清，Layout.vue 早就是这么做的，这一处是同一个迁移漏下的。
const userStore = useUserStore()

const submitting = ref(false)
const formRef = ref()
const form = reactive({
  oldPassword: '',
  newPassword: '',
  confirmPassword: ''
})

const validatePass = (rule, value, callback) => {
  if (value === '') {
    callback(new Error('请确认密码'))
  } else {
    if (value !== form.newPassword) {
      callback(new Error('确认密码跟新密码不一致'))
    } else {
      callback()
    }
  }
}

const rules = {
  // 原密码不卡长度：老账号里存着当年没卡过长度的短密码，卡了等于把人锁在门外。
  // 后端那条路（LoginPassword）也是同样的取舍。
  oldPassword: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    // 下限跟后端 PASSWORD_MIN_LENGTH 对齐。上限（72 字节）交给后端：
    // 前端要按 UTF-8 字节数数（一个汉字 3 字节），用 max 会按字符数卡，对不上。
    { min: 3, message: '密码至少 3 位', trigger: 'blur' }
  ],
  confirmPassword: [{ validator: validatePass, message: '请确认新密码', trigger: 'blur' }]
}

const handleSubmit = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    const res = await updatePasswordApi({
      old_password: form.oldPassword,
      new_password: form.newPassword
    })
    if (res.code === 200) {
      // 后端这次改密码会把本账号的 token_version +1，当前这枚令牌已经作废了
      //（别的设备上的也一样），所以必须以跳登录页收场，不能留在原地。
      ElMessage.success('修改密码成功，请重新登录')
      userStore.logout()
      await router.push('/login')
    }
  } finally {
    submitting.value = false
  }
}
</script>
