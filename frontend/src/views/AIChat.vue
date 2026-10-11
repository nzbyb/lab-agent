<template>
  <div>
    <el-card class="chat-card" shadow="never">
      <template #header>
        <div class="chat-head">
          <div class="app-card-title">
            <span>AI智能助手</span>
          </div>
          <el-button
            link
            type="primary"
            :icon="Delete"
            :disabled="loading || isWelcome"
            @click="clearChat"
            >清空对话</el-button
          >
        </div>
      </template>

      <!-- 聊天记录区。高度交给 .chat-card 的 flex 撑开，不再写死 480px：
           写死会在高屏上留一大片空白，矮屏上又把最后几条消息裁掉。 -->
      <div ref="boxRef" class="chat-box">
        <!-- 空态：一个问题都还没问过时，不显示那条孤零零的欢迎气泡，
             改成一块有引导的起始面板——顺带把系统能做什么摆到明面上。 -->
        <div v-if="isWelcome" class="welcome">
          <div class="welcome-icon">
            <el-icon><MagicStick /></el-icon>
          </div>
          <div class="welcome-title">我是实验室助手小田</div>
          <div class="welcome-desc">
            可以问我实验室的开放时间和空闲时段，也可以直接让我帮你预约。
          </div>
          <div class="welcome-chips">
            <button
              v-for="(question, i) in SUGGESTIONS"
              :key="i"
              class="welcome-chip"
              @click="fillInput(question)"
            >
              {{ question }}
            </button>
          </div>
        </div>

        <div
          v-for="(item, index) in visibleMessages"
          :key="index"
          class="msg-row"
          :class="item.role === 'user' ? 'is-user' : 'is-bot'"
        >
          <!-- 头像：助手用品牌图标；用户优先用登录头像，取不到退回姓名首字 -->
          <div class="msg-avatar">
            <img
              v-if="item.role === 'user' && userStore.userInfo?.avatar"
              :src="userStore.userInfo.avatar"
              alt=""
            />
            <span v-else-if="item.role === 'user'">{{ userInitial }}</span>
            <el-icon v-else><MagicStick /></el-icon>
          </div>

          <div class="msg-main">
            <div class="msg-meta">
              <span>{{ senderName(item) }}</span>
              <span v-if="item.time" class="msg-time">{{ item.time }}</span>
            </div>

            <div class="bubble">
              <!-- 当前进行中的一句话，如「正在思考...」。一旦有工具调用，
                   这个位置就交给下面的执行时间线，避免和步骤里的「进行中」重复。 -->
              <div
                v-if="item.role === 'assistant' && item.status && !item.steps?.length"
                class="bubble-status"
              >
                {{ item.status }}
              </div>

              <!-- 本轮的工具调用过程。运行中默认展开——要能当场看到 Agent 在查什么；
                   本轮结束自动收起成一行摘要。 -->
              <div v-if="item.role === 'assistant' && item.steps?.length" class="trace">
                <div class="trace-head" @click="toggleTrace(item)">
                  <el-icon class="trace-head-icon"><MagicStick /></el-icon>
                  <span class="trace-title">执行过程</span>
                  <span class="trace-count">{{ item.steps.length }} 步</span>
                  <el-icon v-if="isRunning(item)" class="is-loading trace-spin">
                    <Loading />
                  </el-icon>
                  <span class="trace-summary">{{ stepSummary(item) }}</span>
                  <el-icon class="trace-chevron" :class="{ 'is-open': item.stepsOpen }">
                    <ArrowRight />
                  </el-icon>
                </div>

                <div v-show="item.stepsOpen" class="trace-body">
                  <div v-for="(step, i) in item.steps" :key="i" class="trace-step">
                    <div class="trace-icon">
                      <el-icon v-if="step.state === 'running'" class="is-loading trace-spin">
                        <Loading />
                      </el-icon>
                      <el-icon v-else class="trace-ok"><CircleCheckFilled /></el-icon>
                    </div>
                    <div class="trace-content">
                      <div class="trace-label">
                        <span>{{ step.label }}</span>
                        <span v-if="previewSummary(step.preview)" class="trace-tag">
                          {{ previewSummary(step.preview) }}
                        </span>
                      </div>
                      <!-- preview 是工具的返回值，一律走文本插值，绝不 v-html：
                           它来自数据库内容，渲染成 HTML 就等于开了个注入口子。 -->
                      <div
                        v-if="step.preview"
                        class="trace-preview"
                        :class="{ 'is-expanded': step.expanded }"
                        :title="step.expanded ? '点击收起' : '点击展开'"
                        @click="step.expanded = !step.expanded"
                      >
                        {{ previewText(step.preview) }}
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 已过 DOMPurify 消毒，见 parseMarkdown -->
              <div class="md" v-html="parseMarkdown(item.content)"></div>
            </div>
          </div>
        </div>
      </div>

      <div class="composer">
        <el-input
          ref="inputRef"
          v-model="input"
          type="textarea"
          :rows="2"
          :maxlength="MAX_MESSAGE_CHARS"
          show-word-limit
          placeholder="问问实验室怎么预约,开放时间..."
          @keydown.enter.exact.prevent="handleSend"
        >
        </el-input>
        <el-button
          type="primary"
          :icon="Promotion"
          :disabled="!input.trim()"
          :loading="loading"
          @click="handleSend"
          >发送</el-button
        >
      </div>
      <div class="composer-hint">Enter 发送 · Shift+Enter 换行</div>
    </el-card>
  </div>
</template>
<script setup>
import { chatStreamApi } from '@/api/ai'
import { computed, nextTick, reactive, ref } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { ElMessage } from 'element-plus'
import {
  ArrowRight,
  CircleCheckFilled,
  Delete,
  Loading,
  MagicStick,
  Promotion
} from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'

// 不要解构：const { userInfo } = useUserStore() 会丢掉响应性
const userStore = useUserStore()

// 没上传过头像时用姓名首字兜底，免得头像位空成一个洞
const userInitial = computed(() => (userStore.userInfo?.name || '我').slice(0, 1))

// 气泡上方的说话人名字。登录信息里没有名字时退成「我」，别显示成空白。
const senderName = (item) => (item.role === 'user' ? userStore.userInfo?.name || '我' : '助手小田')

// 欢迎语抽成常量：清空对话时要还原成这一条。
// 它在空态下并不渲染（由下面的起始面板承担引导），但仍然留在 messages 里
// 参与 history——保持改造前"模型能看到自己打过招呼"的行为不变。
const WELCOME_MESSAGE = {
  role: 'assistant',
  content:
    '您好,我是实验室助手小田。您可以向我询问怎么预约、取消实验室或者设备。也可以帮你预约实验室。'
}

const messages = ref([WELCOME_MESSAGE])
const input = ref('')
const loading = ref(false)
const boxRef = ref()
const inputRef = ref()

// 空态：只剩那条欢迎语，说明这轮对话还没开始
const isWelcome = computed(() => messages.value.length <= 1)

// 空态时隐藏 messages[0]，改由起始面板承担引导。
// 注意它仍然留在 messages 里——它本来就参与 history（模型能看到自己打过招呼），
// 这里只是不渲染，没有改变发给模型的内容。
const visibleMessages = computed(() => (isWelcome.value ? messages.value.slice(1) : messages.value))

// 起始面板上的示例问题。点击只填入输入框、不自动发送：
// 连点几个 chip 就会撞上后端 20 次/分钟的限流，而且"点一下立刻发出去"
// 太容易误触。填好，让用户自己按发送。
const SUGGESTIONS = [
  '现在有哪些实验室开放？',
  '明天下午 2 点哪个实验室有空？',
  '帮我预约明天上午 9 点的软件工程实验室'
]

const fillInput = (text) => {
  input.value = text
  inputRef.value?.focus()
}

const clearChat = () => {
  // 流式生成中不允许清空：对象虽然从列表里移除了，SSE 回调还会继续往它身上
  // 追加 token——白跑一场，而且用户会看到"点了没反应"。
  // 按钮同时置了 disabled，这里再拦一道。
  if (loading.value) return
  messages.value = [{ ...WELCOME_MESSAGE }]
  input.value = ''
}

// 跟后端 app/schemas/ai.py 的 _MAX_USER_CONTENT 对齐。
// 两头都卡住，超长消息才会在输入框就被拦下来，而不是发出去吃一个 422。
const MAX_MESSAGE_CHARS = 2000

// 消息时间戳只存在前端：下面回传 history 时只取 role/content，
// 所以它既不会污染请求体，也不占后端上下文。
const nowTime = () => {
  const now = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(now.getHours())}:${pad(now.getMinutes())}`
}

const scrollToBottom = () => {
  nextTick(() => {
    const elem = boxRef.value
    if (elem) elem.scrollTop = elem.scrollHeight
  })
}

const handleSend = async () => {
  const text = input.value.trim()
  if (!text || loading.value) return

  messages.value.push({ role: 'user', content: text, time: nowTime() })
  input.value = ''
  loading.value = true
  scrollToBottom()

  // 必须用 reactive: 普通对象 push 后再改字段，视图可能不更新
  const assistant = reactive({
    role: 'assistant',
    content: '', // 正文：靠 token 一点点拼
    status: '正在思考...', // 当前状态文案
    // 工具调用过程。刻意不是字符串数组，而是结构化的对象数组：
    // 每一步要能分别渲染「进行中 / 已完成」两种状态，还要把返回值挂到
    // 对应的那一步上——拼成 "开始: X" / "完成: X" 两行就做不到这些。
    steps: [],
    stepsOpen: true, // 运行中默认展开，让用户当场看到 Agent 在干活
    stepsTouched: false, // 用户手动开合过，本轮结束就不再自动收起
    time: nowTime()
  })
  messages.value.push(assistant)
  const assistantIndex = messages.value.length - 1

  // 只回传最近 20 条：后端也只把最近 20 条送进模型，
  // 传全量既白费流量，也会让请求体随对话越滚越大。
  // 空白 content 必须滤掉——不止刚 push 的这个空助手，上一轮出错留下的
  // 空气泡也一样，留着会让之后每一次请求都吃 422，对话就再也发不出去了。
  const history = messages.value
    .filter(
      (item) =>
        (item.role === 'user' || item.role === 'assistant') &&
        typeof item.content === 'string' &&
        item.content.trim()
    )
    .slice(-20)
    // 只保留 role/content; status、steps、time 丢掉
    .map(({ role, content }) => ({ role, content }))

  try {
    // 第二个参数是回调：每解析出一条 SSE 事件就进一次
    await chatStreamApi({ messages: history }, (evt) => {
      if (evt.type === 'status') {
        assistant.status = evt.message || '正在思考...'
      } else if (evt.type === 'tool_start') {
        const label = evt.label || evt.name || '工具'
        assistant.status = `正在${label}...`
        assistant.steps.push({
          name: evt.name || '',
          label,
          state: 'running',
          preview: '',
          expanded: false
        })
      } else if (evt.type === 'tool_end') {
        const label = evt.label || evt.name || '工具'
        assistant.status = `${label}完成`
        const step = findRunningStep(assistant.steps, evt.name)
        if (step) {
          step.state = 'done'
          step.preview = evt.preview || ''
        } else {
          // 没配上（正常不该发生）也要把这一步记下来：
          // 宁可多显示一步，也不要让过程凭空少一段。
          assistant.steps.push({
            name: evt.name || '',
            label,
            state: 'done',
            preview: evt.preview || '',
            expanded: false
          })
        }
      } else if (evt.type === 'token') {
        assistant.content += evt.content || '' // 打字机：追加，不是覆盖
        assistant.status = '' // 开始出字后清掉「正在...」，避免叠在一起
      } else if (evt.type === 'done') {
        assistant.status = ''
        // 注意: 不要在这里再 append 一整段正文，否则会双份
      } else if (evt.type === 'error') {
        assistant.status = ''
        if (!assistant.content) {
          assistant.content = evt.message || '请求失败'
        }
        ElMessage.error(evt.message || '请求失败')
      }
      scrollToBottom()
    })
  } catch (err) {
    assistant.status = ''
    if (!assistant.content) {
      assistant.content = err.message || '网络异常'
    }
    ElMessage.error(err.message || '网络异常')
  } finally {
    loading.value = false
    assistant.status = ''
    // 本轮结束把过程收起成一行摘要。用户手动点开过就不动它——刚点开就被
    // 合上是比"没收起"更烦人的体验。
    if (!assistant.stepsTouched) assistant.stepsOpen = false
    // 这一轮什么都没产出（网络断了，或后端第一条就是 error）就把空气泡收掉，
    // 免得对话里留一个空白框。有 steps 的留着——那是这轮真实发生过的过程。
    if (!assistant.content && !assistant.steps?.length) {
      messages.value.splice(assistantIndex, 1)
    }
    scrollToBottom()
  }
}

// ---------------------------------------------------------------------------
// 工具调用过程的展示辅助
// ---------------------------------------------------------------------------

// 把 tool_end 配到它对应的那条 tool_start 上。
// 从后往前找「还在跑、且工具名相同」的那条：同一轮里同一个工具可能被调用多次
// （比如反复查不同日期的空闲时段），只按名字找会配错；工具是串行执行的，
// 所以「最后一个还在跑的」就是它。
const findRunningStep = (steps, name) => {
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    if (steps[i].state === 'running' && (!name || steps[i].name === name)) return steps[i]
  }
  // 名字对不上时（比如后端改了工具名）退一步，认最后一个还在跑的
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    if (steps[i].state === 'running') return steps[i]
  }
  return null
}

const toggleTrace = (item) => {
  item.stepsOpen = !item.stepsOpen
  // 记下用户手动开合过，本轮结束时就不再自动收起
  item.stepsTouched = true
}

const isRunning = (item) => item.steps.some((step) => step.state === 'running')

// 收起时那一行摘要：去重后的工具名，如「检索实验室知识库 · 查询空闲时段」
const stepSummary = (item) => [...new Set(item.steps.map((step) => step.label))].join(' · ')

// preview 是工具返回值，多半是后端 json.dumps 出来的紧凑 JSON（工具都这么返回）。
// 能解析就缩进后展示——读起来像一张表，而不是一长串挤在一起的字符。
// 注意后端只截前 200 字符，超长的 JSON 必然解析失败，那就原样显示，不报错。
const previewParsed = (preview) => {
  if (!preview) return undefined
  try {
    return JSON.parse(preview)
  } catch {
    return undefined
  }
}

const previewSummary = (preview) => {
  const parsed = previewParsed(preview)
  if (Array.isArray(parsed)) return `返回 ${parsed.length} 条`
  if (parsed && typeof parsed === 'object') return `返回 ${Object.keys(parsed).length} 个字段`
  return ''
}

const previewText = (preview) => {
  const parsed = previewParsed(preview)
  return parsed === undefined ? preview : JSON.stringify(parsed, null, 2)
}

const parseMarkdown = (text) => {
  if (!text) return ''
  const rawHtml = marked.parse(text).replace(/>\n</g, '><').trim()
  return DOMPurify.sanitize(rawHtml)
}
</script>

<style scoped>
/* ---------------------------------------------------------------------------
 * 布局：整张卡片吃掉视口剩下的高度，聊天区在中间伸缩，输入区吸底。
 * 100px = 页头 60px + el-main 上下内边距各 20px（后两者都是 Element Plus 默认值）。
 * ------------------------------------------------------------------------- */
.chat-card {
  height: calc(100vh - 100px);
  /* 矮窗口兜底：低于这个高度就不再压聊天区，让 el-main 自己去滚 */
  min-height: 420px;
  display: flex;
  flex-direction: column;
  border-radius: var(--app-radius-lg);
}
/* el-card 的 body 是子组件内部节点，拿不到 scoped 属性，必须 :deep。
   flex:1 配 min-height:0 是固定高度容器里让子项正确收缩的经典组合：
   少了 min-height:0，flex 子项默认的 min-height:auto 会把它撑破，滚动条就不出现。 */
.chat-card :deep(.el-card__body) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

/* 卡片头：标题左、操作右 */
.chat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.chat-box {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 4px;
  background-color: var(--app-bg-page);
  border-radius: var(--app-radius-md);
}

/* ---------------------------------------------------------------------------
 * 空态起始面板
 *
 * 改造前这里是一条孤零零的欢迎气泡 + 一大片空白，第一屏什么都不说。
 * 现在把"我是谁、能干什么、你可以这样问"三件事摆出来，并给几个能直接点的
 * 入口——示例问题同时也是能力清单。
 * ------------------------------------------------------------------------- */
.welcome {
  height: 100%;
  /* 矮窗口兜底：内容比聊天区高时让 .chat-box 去滚，不把它压扁 */
  min-height: 280px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 0 16px;
  text-align: center;
}
.welcome-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 52px;
  height: 52px;
  margin-bottom: 14px;
  font-size: 26px;
  color: var(--app-primary);
  background-color: var(--el-color-primary-light-9);
  border-radius: 50%;
}
.welcome-title {
  font-size: 17px;
  font-weight: 600;
  color: var(--app-text-primary);
}
.welcome-desc {
  max-width: 420px;
  margin-top: 8px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--app-text-secondary);
}
.welcome-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
  margin-top: 20px;
}
.welcome-chip {
  padding: 7px 14px;
  font: inherit;
  font-size: 13px;
  color: var(--app-text-primary);
  background-color: #fff;
  border: 1px solid var(--app-border);
  border-radius: 16px;
  cursor: pointer;
  transition:
    border-color 0.2s,
    color 0.2s;
}
.welcome-chip:hover {
  color: var(--app-primary);
  border-color: var(--app-primary);
}

/* 消息行：助手头像在左；用户整行翻转，头像落到右边 */
.msg-row {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}
.msg-row.is-user {
  flex-direction: row-reverse;
}

.msg-avatar {
  flex: 0 0 auto;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: #fff;
  background-color: var(--app-primary);
}
/* 助手用浅底 + 主色图标，跟用户那块实心主色区分开，一眼看得出谁在说话 */
.is-bot .msg-avatar {
  background-color: var(--el-color-primary-light-9);
  color: var(--app-primary);
  font-size: 17px;
}
.is-user .msg-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.msg-main {
  min-width: 0; /* 少了它，长代码块会把气泡顶出容器 */
  max-width: 76%;
  display: flex;
  flex-direction: column;
}
.is-user .msg-main {
  align-items: flex-end;
}

.msg-meta {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-bottom: 4px;
  font-size: 12px;
  color: var(--app-text-secondary);
}
.is-user .msg-meta {
  flex-direction: row-reverse;
}
.msg-time {
  font-size: 11px;
}

/* 气泡：助手白底 + 描边。改造前是 #fff 压在 #fafafa 上，两者差不到
   一个色阶，气泡边界几乎看不见，一整屏看下来像一坨没有形状的灰块。 */
.bubble {
  padding: 10px 12px;
  border: 1px solid var(--app-border);
  border-radius: 12px;
  background-color: #fff;
  color: var(--app-text-primary);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  /* 贴头像的那个角收小，给气泡一个朝向说话人的方向感 */
  border-top-left-radius: 4px;
}
.is-user .bubble {
  background-color: var(--app-primary);
  border-color: var(--app-primary);
  color: #fff;
  border-top-left-radius: 12px;
  border-top-right-radius: 4px;
}

.bubble-status {
  margin-bottom: 6px;
  font-size: 12px;
  color: var(--app-text-secondary);
}
.is-user .bubble-status {
  color: rgba(255, 255, 255, 0.8);
}

/* ---------------------------------------------------------------------------
 * 工具调用执行时间线
 *
 * 这一页真正想让人看见的就是这块：LangGraph 的 ReAct 过程——调了哪些工具、
 * 按什么顺序、每个工具返回了什么。改造前它是一行 12px 的灰字流水
 * （"开始: X" / "完成: X" / "输出结果: ..."），等于把唯一的技术展示点藏了。
 * ------------------------------------------------------------------------- */
.trace {
  margin-bottom: 8px;
  padding: 6px 10px;
  background-color: var(--el-color-primary-light-9);
  border: 1px solid var(--el-color-primary-light-8);
  border-left: 2px solid var(--app-primary);
  border-radius: 8px;
  /* 气泡上带 pre-wrap（为了普通文本消息的换行），这里必须复位，
     否则面板里每个元素的模板空白都会被渲染成真实换行 */
  white-space: normal;
}

.trace-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--app-text-secondary);
  cursor: pointer;
  user-select: none;
}
.trace-head-icon {
  flex: 0 0 auto;
  font-size: 14px;
  color: var(--app-primary);
}
.trace-title {
  flex: 0 0 auto;
  font-weight: 600;
  color: var(--app-text-primary);
}
.trace-count {
  flex: 0 0 auto;
}
/* 收起后的那一行摘要，长了自己省略，不换行把面板顶高 */
.trace-summary {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}
.trace-chevron {
  flex: 0 0 auto;
  font-size: 12px;
  transition: transform 0.2s;
}
.trace-chevron.is-open {
  transform: rotate(90deg);
}
.trace-spin {
  color: var(--app-primary);
}

.trace-body {
  margin-top: 8px;
}

.trace-step {
  position: relative;
  display: flex;
  gap: 8px;
  padding-bottom: 10px;
}
.trace-step:last-child {
  padding-bottom: 0;
}
/* 竖向导轨：从当前图标下沿连到下一步，最后一步不画 */
.trace-step:not(:last-child)::before {
  content: '';
  position: absolute;
  left: 9px;
  top: 20px;
  bottom: 0;
  width: 1px;
  background-color: var(--el-color-primary-light-7);
}

.trace-icon {
  flex: 0 0 auto;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
}
.trace-ok {
  color: var(--app-status-approved);
}

.trace-content {
  flex: 1;
  min-width: 0;
}
.trace-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 500;
  line-height: 20px;
  color: var(--app-text-primary);
}
/* 「返回 N 条」这种一行摘要 */
.trace-tag {
  flex: 0 0 auto;
  padding: 0 6px;
  font-size: 11px;
  font-weight: 400;
  line-height: 16px;
  color: var(--app-text-secondary);
  background-color: #fff;
  border: 1px solid var(--app-border);
  border-radius: 8px;
}

/* 工具返回值：默认一行截断，点一下展开全文 */
.trace-preview {
  margin-top: 4px;
  padding: 6px 8px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.5;
  color: var(--app-text-primary);
  background-color: #f6f8fa;
  border: 1px solid var(--app-border);
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/* 展开后换行显示，超过 280px 内部滚动，不把气泡顶得老长 */
.trace-preview.is-expanded {
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 280px;
  overflow: auto;
}

/* ---------------------------------------------------------------------------
 * Markdown 正文样式
 *
 * 这些元素都由 v-html 产出，不携带 scoped 属性，所以每条都得走 :deep()。
 *
 * 圆点和链接这两条是**修 bug**，不是美化：
 *   - global.css 有一条 `ul,ol{list-style:none}` 的 reset，把助手回答里的列表
 *     圆点全抹了，模型分点回答时看起来就是几行散句；
 *   - 还有一条 `a{color:inherit;text-decoration:none}`，回答里的链接和正文
 *     同色、无下划线，根本看不出是链接。
 * 修在 scoped 里而不是改 global.css：那两条 reset 被全部 15 个页面共用，
 * 在这里覆盖的影响面只有这一页。
 * ------------------------------------------------------------------------- */
.md :deep(> :first-child) {
  margin-top: 0;
}
.md :deep(> :last-child) {
  margin-bottom: 0;
}
.md :deep(p + p) {
  margin-top: 8px;
}
.md :deep(ul),
.md :deep(ol) {
  margin: 8px 0;
  padding-left: 22px;
}
.md :deep(ul) {
  list-style: disc;
}
.md :deep(ol) {
  list-style: decimal;
}
.md :deep(li + li) {
  margin-top: 4px;
}
.md :deep(h1),
.md :deep(h2),
.md :deep(h3),
.md :deep(h4) {
  margin: 14px 0 6px;
  font-weight: 600;
  line-height: 1.4;
}
.md :deep(h1) {
  font-size: 18px;
}
.md :deep(h2) {
  font-size: 16px;
}
.md :deep(h3) {
  font-size: 15px;
}
.md :deep(h4) {
  font-size: 14px;
}
.md :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Courier New', monospace;
  font-size: 12.5px;
  padding: 1px 4px;
  border-radius: 4px;
  background-color: var(--app-bg-muted);
}
.md :deep(pre) {
  margin: 10px 0;
  padding: 10px 12px;
  max-height: 320px;
  overflow: auto;
  background-color: #f6f8fa;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}
.md :deep(pre code) {
  padding: 0;
  background-color: transparent;
  font-size: 12.5px;
  line-height: 1.6;
  /* 代码块里保持原样换行，不继承气泡的 pre-wrap，否则会多出一层空行 */
  white-space: pre;
}
.md :deep(blockquote) {
  margin: 10px 0;
  padding: 2px 0 2px 10px;
  border-left: 3px solid var(--app-border-strong);
  color: var(--app-text-secondary);
}
.md :deep(table) {
  width: 100%;
  margin: 10px 0;
  border-collapse: collapse;
  font-size: 13px;
}
.md :deep(th),
.md :deep(td) {
  padding: 6px 10px;
  border: 1px solid var(--app-border);
  text-align: left;
}
.md :deep(th) {
  background-color: var(--app-bg-muted);
  font-weight: 600;
}
.md :deep(a) {
  color: var(--app-primary);
  text-decoration: underline;
  text-underline-offset: 2px;
}
/* 用户气泡是主色实心底，链接得跟着变白才看得见 */
.is-user .bubble .md :deep(a) {
  color: inherit;
}
.md :deep(hr) {
  margin: 12px 0;
  border: none;
  border-top: 1px solid var(--app-border);
}
.md :deep(img) {
  border-radius: var(--app-radius-md);
}

/* ---------------------------------------------------------------------------
 * 输入区
 * ------------------------------------------------------------------------- */
.composer {
  flex: 0 0 auto;
  display: flex;
  gap: 10px;
  align-items: flex-end;
  margin-top: 12px;
}
/* el-input 的根节点会带上父组件的 scoped 属性，所以这里不需要 :deep */
.composer .el-textarea {
  flex: 1;
  min-width: 0;
}
/* 去掉浏览器给 textarea 加的右下角拖拽把手：它和卡片圆角打架，
   截图上就是一道斜线，是「没做完」最明显的信号之一 */
.composer :deep(.el-textarea__inner) {
  resize: none;
}
.composer-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--app-text-secondary);
  text-align: right;
}
</style>
