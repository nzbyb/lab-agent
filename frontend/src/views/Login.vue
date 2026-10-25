<template>
  <div class="auth-page">
    <!-- 左：品牌区。跟注册页共用 components/AuthBrandPanel.vue，
         窄屏下变成顶部横幅（样式在那个组件里）。 -->
    <AuthBrandPanel />

    <!-- 右：登录表单。密码登录同时接受账号和手机号，另一种是邮箱验证码。 -->
    <div class="auth-form-panel">
      <div class="auth-form-inner">
        <h2 class="auth-form-title">欢迎回来</h2>
        <p class="auth-form-subtitle">请选择一种登录方式</p>

        <el-tabs v-model="loginMode" class="login-tabs" stretch>
          <el-tab-pane label="密码登录" name="password">
            <!-- name 必须显式写：el-input 声明了 name prop，但不传就是 undefined，
                 渲染出来的 <input> 上根本没有 name 属性（实测过）。autocomplete 是
                 "这个字段是什么"的语义提示，name 才是密码管理器和浏览器自动填充
                 一直在认的传统信号，两个一起给才稳。
                 另外 el-form 渲染成的是真的 <form>，但 el-button 的 native-type 默认是
                 button，所以这个表单里没有提交按钮。回车提交由下面两个 @keyup.enter
                 显式处理。 -->
            <el-form
              ref="passwordFormRef"
              :rules="passwordRules"
              :model="passwordForm"
              label-width="0px"
              class="login-form"
              @submit.prevent
            >
              <el-form-item prop="account">
                <!-- autocapitalize / autocorrect / spellcheck 三条一起关掉。
                     账号是**一字不差**比对的（后端 `User.username == 提交值`），而手机上的软键盘
                     默认会把句首字母自动大写、还会"顺手纠正"拼写：`demo` 变成 `Demo`，登录就报
                     "账号或密码错误"——报错和真实原因对不上，用户很难自己想明白。
                     上面既然给了 name/autocomplete 让浏览器更愿意自动填充，这三条就更不能省。 -->
                <el-input
                  size="large"
                  v-model="passwordForm.account"
                  placeholder="账号或手机号"
                  :prefix-icon="User"
                  autofocus
                  name="username"
                  autocomplete="username"
                  autocapitalize="off"
                  autocorrect="off"
                  spellcheck="false"
                  @keyup.enter="loginWithPassword"
                />
              </el-form-item>
              <el-form-item prop="password">
                <el-input
                  type="password"
                  size="large"
                  v-model="passwordForm.password"
                  placeholder="请输入密码"
                  :prefix-icon="Lock"
                  show-password
                  name="password"
                  autocomplete="current-password"
                  autocapitalize="off"
                  autocorrect="off"
                  @keyup.enter="loginWithPassword"
                />
              </el-form-item>
              <!-- 只挂在密码登录这一栏：邮箱验证码登录的人本来就能收信，
                   不需要"找回密码"这条路。 -->
              <div class="login-forgot">
                <router-link to="/forgot-password">忘记密码？</router-link>
              </div>
              <el-button
                size="large"
                type="primary"
                class="auth-submit"
                @click="loginWithPassword"
                :loading="passwordLoading"
                >登 录</el-button
              >
            </el-form>
          </el-tab-pane>

          <el-tab-pane label="邮箱验证码" name="email">
            <el-form
              ref="emailFormRef"
              :rules="emailRules"
              :model="emailForm"
              label-width="0px"
              class="login-form"
              @submit.prevent
            >
              <el-form-item prop="email">
                <el-input
                  size="large"
                  v-model="emailForm.email"
                  placeholder="QQ 邮箱"
                  :prefix-icon="Message"
                  name="email"
                  autocomplete="email"
                  autocapitalize="off"
                  autocorrect="off"
                  spellcheck="false"
                  @keyup.enter="sendEmailCode"
                />
              </el-form-item>
              <el-form-item prop="code">
                <div class="code-row">
                  <el-input
                    size="large"
                    v-model="emailForm.code"
                    placeholder="6 位验证码"
                    maxlength="6"
                    name="one-time-code"
                    autocomplete="one-time-code"
                    inputmode="numeric"
                    @keyup.enter="loginWithEmailCode"
                  />
                  <el-button
                    class="code-button"
                    size="large"
                    :loading="sendingCode"
                    :disabled="countdown > 0 || sendingCode"
                    @click="sendEmailCode"
                  >
                    {{ countdown > 0 ? `${countdown} 秒` : '获取验证码' }}
                  </el-button>
                </div>
              </el-form-item>
              <el-button
                size="large"
                type="primary"
                class="auth-submit"
                @click="loginWithEmailCode"
                :loading="emailLoading"
                >登 录</el-button
              >
            </el-form>
          </el-tab-pane>
        </el-tabs>

        <div class="auth-form-footer">
          还没有账号？<router-link to="/register">立即注册</router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref, onBeforeUnmount } from 'vue'
import { User, Lock, Message } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import AuthBrandPanel from '@/components/AuthBrandPanel.vue'
import router from '@/router'
import { loginApi, loginByPhoneApi, sendEmailCodeApi, loginByEmailCodeApi } from '@/api/auth'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()

// 密码这一栏同时收账号和手机号。后端是两条接口：长得像手机号就走手机号登录，
// 否则按账号登录。这样界面上不用再多一个标签页，用户也不用先想"我这是哪种账号"。
const PHONE_RE = /^1[3-9]\d{9}$/

const loginMode = ref('password')
const passwordFormRef = ref()
const emailFormRef = ref()

const passwordForm = reactive({
  account: '',
  password: ''
})

const emailForm = reactive({
  email: '',
  code: ''
})

const passwordLoading = ref(false)
const emailLoading = ref(false)
const sendingCode = ref(false)
const countdown = ref(0)
let countdownTimer = null

const passwordRules = {
  account: [{ required: true, message: '请输入账号或手机号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

const emailRules = {
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' }
  ],
  code: [
    { required: true, message: '请输入验证码', trigger: 'blur' },
    { pattern: /^\d{6}$/, message: '请输入 6 位数字验证码', trigger: 'blur' }
  ]
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

const finishLogin = async (res) => {
  if (res.code === 200) {
    userStore.saveLoginData(res.data)
    ElMessage.success('登录成功')
    await router.push('/manager/home')
  }
}

const loginWithPassword = async () => {
  const valid = await passwordFormRef.value.validate().catch(() => false)
  if (!valid) {
    return
  }
  const account = passwordForm.account.trim()
  // 跟后端 normalize_phone 一样，先容忍用户从别处粘贴进来的空格和横线
  const phone = account.replace(/[\s-]/g, '')
  passwordLoading.value = true
  try {
    const res = PHONE_RE.test(phone)
      ? await loginByPhoneApi({ phone, password: passwordForm.password })
      : await loginApi({ username: account, password: passwordForm.password })
    await finishLogin(res)
  } catch {
    // 失败提示由 request 拦截器统一弹出（业务错误走 HTTP 200 + body.code）。
    // 这里只吞掉 rejection，防止控制台出现未捕获异常。
  } finally {
    passwordLoading.value = false
  }
}

const sendEmailCode = async () => {
  // 只校验邮箱这一项，不要求验证码先填好——用户就是还没收到码才来点它。
  const valid = await emailFormRef.value
    .validateField('email')
    .then(() => true)
    .catch(() => false)
  if (!valid) {
    return
  }
  sendingCode.value = true
  try {
    const res = await sendEmailCodeApi({ email: emailForm.email.trim() })
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

const loginWithEmailCode = async () => {
  const valid = await emailFormRef.value.validate().catch(() => false)
  if (!valid) {
    return
  }
  emailLoading.value = true
  try {
    const res = await loginByEmailCodeApi({
      email: emailForm.email.trim(),
      code: emailForm.code.trim()
    })
    await finishLogin(res)
  } catch {
    // 同上：提示已由 request 拦截器统一处理。
  } finally {
    emailLoading.value = false
  }
}
</script>

<style scoped>
/* 左右分栏的外框、右侧表单的标题与主按钮等共用样式都在 global.css 的
   「登录 / 注册页的公共骨架」一节；这里只留登录页独有的标签栏和验证码行。 */
.login-tabs {
  width: 100%;
}

/* 标签栏和表单之间留一点呼吸，别让输入框贴着标签下划线 */
.login-tabs :deep(.el-tabs__header) {
  margin-bottom: 22px;
}

.login-form {
  width: 100%;
}

/* 密码框和登录按钮之间的那一行。负 margin 把 el-form-item 自带的下边距
   抵掉一点，不然按钮会离密码框太远，看起来像两段。 */
.login-forgot {
  margin: -6px 0 16px;
  text-align: right;
  font-size: 13px;
}

.login-forgot a {
  color: var(--el-color-primary);
}

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
