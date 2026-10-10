<template>
  <div class="login-container">
    <div class="login-box">
      <h1>实验室预约系统</h1>
      <div style="margin-top: 5px; margin-bottom: 30px">基于Ai Agent智能预约系统</div>

      <el-form ref="formRef" :rules="rules" :model="form" label-width="0px" style="width: 100%">
        <el-form-item prop="username">
          <el-input
            size="large"
            v-model="form.username"
            placeholder="请输入账号"
            :prefix-icon="User"
          />
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
        <div>
          <el-button
            size="large"
            type="primary"
            style="width: 100%"
            @click="login"
            :loading="loadingValue"
            >登 录</el-button
          >
          <div style="text-align: right; margin-top: 20px">
            还没有账号? 请<router-link style="color: var(--el-color-primary)" to="/register"
              >注册</router-link
            >
          </div>
        </div>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { User, Lock } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import router from '@/router'
import { loginApi } from '@/api/auth'
import { useUser } from '@/utils/user'

const { saveLoginData } = useUser()

const formRef = ref()

const form = reactive({
  username: '',
  password: ''
})

const loadingValue = ref(false)

const rules = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

const login = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) {
    return
  }
  loadingValue.value = true
  try {
    const res = await loginApi(form)

    if (res.code === 200) {
      saveLoginData(res.data)
      ElMessage.success('登录成功')
      await router.push('/manager/home')
      // 登录逻辑
    }
  } finally {
    loadingValue.value = false
  }
}
</script>

<style scoped>
.login-container {
  height: 100vh;
  display: flex;
  justify-content: center;
  align-items: center;
}
/* 原本这个字号写成 <h1 font-size: 28px>，是个不生效的无效 HTML 属性。
   巧合的是 h1 默认 2em、body 是 14px，算下来正好 28px，所以看起来"没坏"。
   这里显式写出来，别再靠巧合。 */
.login-box h1 {
  font-size: 28px;
}
.login-box {
  width: 380px;
  border-radius: 8px;
  box-shadow: 0 8px 12px rgba(0, 0, 0, 0.1);
  padding: 30px;
  text-align: center;
  background-color: white;
}
</style>
