<template>
  <div class="login-page">
    <!-- 左：品牌区。窄屏下变成顶部横幅，见文件末尾的 @media -->
    <div class="brand-panel">
      <div class="brand-inner">
        <div class="brand-mark">
          <img src="@/assets/imgs/logo.jpg" alt="智能实验室预约系统" />
        </div>
        <h1 class="brand-title">智能实验室预约系统</h1>
        <p class="brand-subtitle">FastAPI + Vue 3 · AI Agent 驱动的实验室预约与管理平台</p>
        <ul class="brand-features">
          <li>
            <el-icon><Calendar /></el-icon>
            <span>在线预约实验室与设备，各时段空闲情况一目了然</span>
          </li>
          <li>
            <el-icon><MagicStick /></el-icon>
            <span>AI 智能助手对话式预约，自动查数据、代提交</span>
          </li>
          <li>
            <el-icon><Reading /></el-icon>
            <span>知识库问答，预约规则与安全规范随手可查</span>
          </li>
          <li>
            <el-icon><DocumentChecked /></el-icon>
            <span>预约审核与账号、设备管理，管理员统一处理</span>
          </li>
        </ul>
      </div>
    </div>

    <!-- 右：登录表单。表单结构和提交逻辑与改造前完全一致 -->
    <div class="form-panel">
      <div class="form-inner">
        <h2 class="form-title">欢迎回来</h2>
        <p class="form-subtitle">请登录你的账号以继续使用</p>

        <el-form ref="formRef" :rules="rules" :model="form" label-width="0px" class="login-form">
          <el-form-item prop="username">
            <el-input
              size="large"
              v-model="form.username"
              placeholder="请输入账号"
              :prefix-icon="User"
              autofocus
              autocomplete="username"
              @keyup.enter="login"
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
              autocomplete="current-password"
              @keyup.enter="login"
            />
          </el-form-item>
          <el-button
            size="large"
            type="primary"
            class="login-button"
            @click="login"
            :loading="loadingValue"
            >登 录</el-button
          >
        </el-form>

        <div class="register-line">
          还没有账号？<router-link class="register-link" to="/register">立即注册</router-link>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { User, Lock, Calendar, MagicStick, Reading, DocumentChecked } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import router from '@/router'
import { loginApi } from '@/api/auth'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()

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
      userStore.saveLoginData(res.data)
      ElMessage.success('登录成功')
      await router.push('/manager/home')
    }
  } catch {
    // 失败提示由 request 拦截器统一弹出（业务错误走 HTTP 200 + body.code）。
    // 两点实情，写在这里是为了不误导下一个读代码的人：
    // 1) 密码输错走的是 body.code=500 且 HTTP 200，拦截器弹完提示后是
    //    return data（resolve），那条路径本来就不会产生未捕获 rejection；
    //    真正会 reject 的是网络不通和 HTTP 4xx/5xx。
    // 2) request.js 里 HTTP 401 那条只 logout + 跳转、不发提示，它的 rejection
    //    也会被这里一并吞掉。正常情况 /api/auth/login 不返回 401，先这样。
  } finally {
    loadingValue.value = false
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  min-height: 100vh;
}

/* ---------------------------------------------------------------------------
 * 左：品牌区
 *
 * 渐变终点取的是 Element Plus 的主色 #409eff，让这块和登录后各页面的主色
 * 是同一个蓝，不是另起一套配色。
 * ------------------------------------------------------------------------- */
.brand-panel {
  position: relative;
  overflow: hidden;
  flex: 1 1 55%;
  display: flex;
  align-items: center;
  /* 右边多留 140px，比下面的渐隐带（120px）宽：把内容挡在渐隐带之外。
   * 少了这 20px 余量，文字右端会飘到正在变白的区域上，白字白底直接消失。 */
  padding: 60px 140px 60px 60px;
  color: #fff;
  /* 第一层（写在前面 = 画在上面）把右边缘 120px 从全透明渐变到纯白，
   * 第二层才是蓝色渐变。叠加结果是蓝色自己溶进白色里——两栏之间不再有
   * 那条硬边，而不是在硬边旁边补一层淡色（上一版就是这么做的，等于没做）。
   * 背景画在子元素之下，所以文字和图标不受影响。 */
  background-image:
    linear-gradient(90deg, rgba(255, 255, 255, 0) calc(100% - 120px), #ffffff 100%),
    linear-gradient(135deg, #1a3d7c 0%, #2f6fd0 55%, #409eff 100%);
}

/* 左下角的两个浅色圆弧，纯装饰 */
.brand-panel::before,
.brand-panel::after {
  content: '';
  position: absolute;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.07);
  pointer-events: none;
}

.brand-panel::before {
  width: 460px;
  height: 460px;
  right: -140px;
  bottom: -200px;
}

.brand-panel::after {
  width: 280px;
  height: 280px;
  right: 60px;
  bottom: -210px;
}

.brand-inner {
  position: relative; /* 压在装饰圆弧之上 */
  z-index: 1;
  width: 100%;
  max-width: 460px;
  margin: 0 auto;
}

/* logo 原图是不透明白底 jpg，直接放渐变上会是一块白方块，
 * 所以垫一个白色圆角块当"app 图标"。 */
.brand-mark {
  width: 84px;
  height: 84px;
  border-radius: 20px;
  background: #fff;
  overflow: hidden;
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.18);
}

/* 原图 1280×1706，实际图形只占 37.5% 宽 × 23.8% 高，四周全是白边，
 * 但图形本身是正居中的（扫像素实测中心 0.498 / 0.498）。
 * 不放大时：object-fit: cover 把图缩成 84×112，可见图形只剩约 31×27px，
 * 占方块 12% 面积——看起来就是"白方块正中一个小绿点"。
 * 按中心放大 2.3 倍 → 约 72×61px，占 62.8% 面积。图形居中（放大后偏移 0.23px），
 * 所以放大不会偏。原图 1280px 宽，放大后每个 CSS 像素仍摊到约 6.6 个源像素
 * （2x 屏 3.3 个），是降采样，不会糊。 */
.brand-mark img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transform: scale(2.3);
}

/* 两级标题的字号都在这里显式写死，不靠 h1/h2 的浏览器默认值。
 * 改造前那版有一个不生效的 <h1 font-size="28px"> HTML 属性，是靠 h1 默认
 * 2em × body 14px 恰好等于 28px 才"看起来没坏"。别再依赖这种巧合。 */
.brand-title {
  font-size: 34px;
  line-height: 1.3;
  letter-spacing: 1px;
}

.brand-subtitle {
  margin-top: 12px;
  font-size: 14px;
  line-height: 1.7;
  color: rgba(255, 255, 255, 0.8);
}

.brand-features {
  margin-top: 30px;
}

.brand-features li {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 0;
  font-size: 15px;
  color: rgba(255, 255, 255, 0.92);
  border-bottom: 1px solid rgba(255, 255, 255, 0.15);
}

.brand-features li:last-child {
  border-bottom: none;
}

/* 图标默认跟着 li 的 15px，比正文还轻；单给到 18px。
 * flex: none 是不让它被右侧长文案挤扁（li 本身是 flex 容器）。 */
.brand-features li .el-icon {
  flex: none;
  font-size: 18px;
}

/* ---------------------------------------------------------------------------
 * 右：登录表单
 * ------------------------------------------------------------------------- */
.form-panel {
  flex: 1 1 45%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  /* 回到纯白：左栏已经自己渐隐到白了，这里再铺一层淡蓝，反倒会在交界处
   * 冒出一条"白 → 淡蓝 → 白"的反向色带。 */
  background-color: #fff;
}

.form-inner {
  width: 100%;
  max-width: 360px;
}

.form-title {
  font-size: 28px;
}

.form-subtitle {
  margin-top: 8px;
  margin-bottom: 30px;
  font-size: 14px;
  color: var(--app-text-secondary);
}

.login-form {
  width: 100%;
}

.login-button {
  width: 100%;
  border-radius: var(--app-radius-md);
}

.register-line {
  margin-top: 20px;
  text-align: right;
  font-size: 14px;
  color: var(--app-text-secondary);
}

.register-link {
  color: var(--el-color-primary);
}

/* ---------------------------------------------------------------------------
 * 窄屏：改成上下堆叠。品牌区只剩 logo + 标题当横幅，特性列表隐藏——
 * 手机上那 4 条会把登录框挤出首屏。
 * ------------------------------------------------------------------------- */
@media (max-width: 900px) {
  .login-page {
    flex-direction: column;
  }

  .brand-panel {
    flex: none;
    /* 竖排后交界线是横的，渐隐带跟着转到底部 */
    padding: 32px 24px 90px;
    background-image:
      linear-gradient(180deg, rgba(255, 255, 255, 0) calc(100% - 80px), #ffffff 100%),
      linear-gradient(135deg, #1a3d7c 0%, #2f6fd0 55%, #409eff 100%);
  }

  .brand-inner {
    max-width: none;
  }

  .brand-mark {
    width: 56px;
    height: 56px;
    border-radius: 14px;
  }

  .brand-title {
    margin-top: 16px;
    font-size: 22px;
  }

  .brand-subtitle,
  .brand-features {
    display: none;
  }

  .form-panel {
    flex: 1;
    padding: 32px 24px 48px;
  }
}
</style>
