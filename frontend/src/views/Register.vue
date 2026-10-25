<template>
  <div class="auth-page">
    <!-- 左：品牌区，跟登录页共用同一个组件 -->
    <AuthBrandPanel />

    <div class="auth-form-panel">
      <div class="auth-form-inner">
        <h2 class="auth-form-title">创建账号</h2>
        <p class="auth-form-subtitle">用邮箱验证码完成注册，之后可直接用邮箱登录</p>
        <el-form ref="formRef" :rules="rules" :model="form" label-width="0px" @submit.prevent>
          <el-form-item prop="username">
            <el-input
              size="large"
              v-model="form.username"
              placeholder="请输入账号"
              :prefix-icon="User"
            />
          </el-form-item>
          <el-form-item prop="email">
            <el-input
              size="large"
              v-model="form.email"
              placeholder="QQ 邮箱"
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
              placeholder="请输入密码"
              :prefix-icon="Lock"
              show-password
            />
          </el-form-item>
          <el-form-item prop="confirmPassword">
            <el-input
              type="password"
              size="large"
              v-model="form.confirmPassword"
              placeholder="请确认密码"
              :prefix-icon="Lock"
              show-password
            />
          </el-form-item>
          <el-button
            size="large"
            type="primary"
            class="auth-submit"
            :loading="loadingValue"
            @click="register"
            >注 册</el-button
          >
        </el-form>

        <div class="auth-form-footer">
          已有账号？<router-link to="/login">立即登录</router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref, onBeforeUnmount } from 'vue'
import { User, Lock, Message } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { registerApi, sendRegisterCodeApi } from '@/api/auth'
import AuthBrandPanel from '@/components/AuthBrandPanel.vue'
import router from '@/router'

const form = reactive({
  username: '',
  email: '',
  code: '',
  password: '',
  confirmPassword: ''
})

const loadingValue = ref(false)
const sendingCode = ref(false)
const countdown = ref(0)
let countdownTimer = null

const formRef = ref()

const validatePass = (rule, value, callback) => {
  if (value === '') {
    callback(new Error('请确认密码'))
  } else {
    if (value !== form.password) {
      callback(new Error('两次密码输入不一致'))
    } else {
      callback()
    }
  }
}

const rules = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' }
  ],
  code: [
    { required: true, message: '请输入验证码', trigger: 'blur' },
    { pattern: /^\d{6}$/, message: '请输入 6 位数字验证码', trigger: 'blur' }
  ],
  // 下限跟后端 PASSWORD_MIN_LENGTH 对齐（3 位）。不加这条的话，输入 1-2 位
  // 密码会一路提交到后端才被拒，弹回来的是「请求参数校验错误」——
  // 用户根本猜不到是密码太短。上限（72 字节）交给后端，理由同 Password.vue。
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
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
  // 只校验邮箱：用户就是还没收到码才来点它，不能要求验证码先填好。
  const valid = await formRef.value
    .validateField('email')
    .then(() => true)
    .catch(() => false)
  if (!valid) {
    return
  }
  sendingCode.value = true
  try {
    const res = await sendRegisterCodeApi({ email: form.email.trim() })
    if (res.code === 200) {
      ElMessage.success('验证码已发送，请查收邮箱')
      startCountdown(res.data?.cooldown)
    }
  } catch {
    // HTTP 429（发信太频繁）和网络异常由 request 拦截器统一提示。
  } finally {
    sendingCode.value = false
  }
}

const register = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) {
    return
  }
  loadingValue.value = true
  try {
    // 只发后端认识的字段；confirmPassword 是前端自己的校验项。
    const res = await registerApi({
      username: form.username.trim(),
      password: form.password,
      email: form.email.trim(),
      code: form.code.trim()
    })

    if (res.code === 200) {
      ElMessage.success('注册成功')
      await router.push('/login')
    }
  } catch {
    // 失败提示由 request 拦截器统一弹出。
  } finally {
    loadingValue.value = false
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
