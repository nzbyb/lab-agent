<template>
  <div class="auth-page">
    <!-- 跟登录页、注册页共用同一块品牌区 -->
    <AuthBrandPanel />

    <div class="auth-form-panel">
      <div class="auth-form-inner">
        <h2 class="auth-form-title">找回密码</h2>
        <p class="auth-form-subtitle">验证绑定的邮箱后，直接设置一个新密码</p>

        <el-form ref="formRef" :rules="rules" :model="form" label-width="0px" @submit.prevent>
          <el-form-item prop="email">
            <el-input
              size="large"
              v-model="form.email"
              placeholder="账号绑定的邮箱"
              :prefix-icon="Message"
              name="email"
              autocomplete="email"
              autocapitalize="off"
              autocorrect="off"
              spellcheck="false"
            />
          </el-form-item>
          <el-form-item prop="code">
            <div class="code-row">
              <el-input
                size="large"
                v-model="form.code"
                placeholder="6 位验证码"
                maxlength="6"
                name="one-time-code"
                autocomplete="one-time-code"
                inputmode="numeric"
              />
              <el-button
                class="code-button"
                size="large"
                :loading="sendingCode"
                :disabled="countdown > 0 || sendingCode"
                @click="sendCode"
              >
                {{ countdown > 0 ? `${countdown} 秒` : '获取验证码' }}
              </el-button>
            </div>
          </el-form-item>
          <el-form-item prop="password">
            <el-input
              type="password"
              size="large"
              v-model="form.password"
              placeholder="请设置新密码"
              :prefix-icon="Lock"
              show-password
              name="new-password"
              autocomplete="new-password"
            />
          </el-form-item>
          <el-form-item prop="confirmPassword">
            <el-input
              type="password"
              size="large"
              v-model="form.confirmPassword"
              placeholder="请确认新密码"
              :prefix-icon="Lock"
              show-password
              name="confirm-password"
              autocomplete="new-password"
            />
          </el-form-item>
          <el-button
            size="large"
            type="primary"
            class="auth-submit"
            :loading="submitting"
            @click="submit"
            >重置密码</el-button
          >
        </el-form>

        <div class="auth-form-footer">
          想起密码了？<router-link to="/login">返回登录</router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref, onBeforeUnmount } from 'vue'
import { Lock, Message } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import AuthBrandPanel from '@/components/AuthBrandPanel.vue'
import router from '@/router'
import { resetPasswordApi, sendResetCodeApi } from '@/api/auth'

const form = reactive({
  email: '',
  code: '',
  password: '',
  confirmPassword: ''
})

const formRef = ref()
const submitting = ref(false)
const sendingCode = ref(false)
const countdown = ref(0)
let countdownTimer = null

const validatePass = (rule, value, callback) => {
  if (value === '') {
    callback(new Error('请确认新密码'))
  } else if (value !== form.password) {
    callback(new Error('两次密码输入不一致'))
  } else {
    callback()
  }
}

const rules = {
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' }
  ],
  code: [
    { required: true, message: '请输入验证码', trigger: 'blur' },
    { pattern: /^\d{6}$/, message: '请输入 6 位数字验证码', trigger: 'blur' }
  ],
  // 下限跟后端 PASSWORD_MIN_LENGTH 对齐；上限（72 字节）交给后端。
  password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 3, message: '密码至少 3 位', trigger: 'blur' }
  ],
  confirmPassword: [{ validator: validatePass, trigger: 'blur' }]
}

const startCountdown = (seconds) => {
  if (countdownTimer) {
    clearInterval(countdownTimer)
  }
  countdown.value = Math.max(1, Number(seconds) || 60)
  countdownTimer = setInterval(() => {
    countdown.value -= 1
    if (countdown.value <= 0) {
      clearInterval(countdownTimer)
      countdownTimer = null
    }
  }, 1000)
}

onBeforeUnmount(() => {
  if (countdownTimer) {
    clearInterval(countdownTimer)
  }
})

const sendCode = async () => {
  // 只校验邮箱：用户就是还没收到码才来点它。
  const valid = await formRef.value
    .validateField('email')
    .then(() => true)
    .catch(() => false)
  if (!valid) {
    return
  }
  sendingCode.value = true
  try {
    const res = await sendResetCodeApi({ email: form.email.trim() })
    if (res.code === 200) {
      ElMessage.success('验证码已发送，请查收邮箱')
      startCountdown(res.data?.cooldown)
    }
  } catch {
    // 失败提示由 request 拦截器统一弹出。
  } finally {
    sendingCode.value = false
  }
}

const submit = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) {
    return
  }
  submitting.value = true
  try {
    const res = await resetPasswordApi({
      email: form.email.trim(),
      code: form.code.trim(),
      new_password: form.password
    })
    if (res.code === 200) {
      // 后端顺手把 token_version +1 了：这个账号此前签发的令牌（包括别的设备）
      // 全部作废。所以这里必须回登录页，不能直接把人送进系统。
      ElMessage.success('密码已重置，请用新密码登录')
      await router.push('/login')
    }
  } catch {
    // 失败提示由 request 拦截器统一弹出。
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
/* 左右分栏和右侧表单的公共样式在 global.css；这里只有验证码这一行。 */
.code-row {
  display: flex;
  gap: 10px;
  width: 100%;
}

.code-row .el-input {
  flex: 1;
  min-width: 0;
}

/* 固定宽度，倒计时变成 "60 秒" 时按钮不会跟着跳 */
.code-button {
  flex: none;
  width: 112px;
}
</style>
