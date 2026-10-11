<template>
  <div>
    <el-card class="chat-card" shadow="never">
      <template #header>
        <div class="app-card-title">
          <span>AI智能助手</span>
        </div>
      </template>

      <!-- 聊天记录区。高度交给 .chat-card 的 flex 撑开，不再写死 480px：
           写死会在高屏上留一大片空白，矮屏上又把最后几条消息裁掉。 -->
      <div ref="boxRef" class="chat-box">
        <div
          v-for="(item, index) in messages"
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
              <!-- 当前进行中的一句话，如「正在查询开放实验室...」 -->
              <div v-if="item.role === 'assistant' && item.status" class="bubble-status">
                {{ item.status }}
              </div>
              <!-- 本轮已发生的过程列表，只展示不回传给后端 -->
              <div v-if="item.role === 'assistant' && item.steps?.length" class="bubble-steps">
                <div v-for="(step, i) in item.steps" :key="i">• {{ step }}</div>
              </div>
              <!-- 已过 DOMPurify 消毒，见 parseMarkdown -->
              <div class="md" v-html="parseMarkdown(item.content)"></div>
            </div>
          </div>
        </div>
      </div>

      <div class="composer">
        <el-input
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
import { MagicStick, Promotion } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'

// 不要解构：const { userInfo } = useUserStore() 会丢掉响应性
const userStore = useUserStore()

// 没上传过头像时用姓名首字兜底，免得头像位空成一个洞
const userInitial = computed(() => (userStore.userInfo?.name || '我').slice(0, 1))

// 气泡上方的说话人名字。登录信息里没有名字时退成「我」，别显示成空白。
const senderName = (item) => (item.role === 'user' ? userStore.userInfo?.name || '我' : '助手小田')

const messages = ref([
  {
    role: 'assistant',
    content:
      '您好,我是实验室助手小田。您可以向我询问怎么预约、取消实验室或者设备。也可以帮你预约实验室。'
  }
])
const input = ref('')
const loading = ref(false)
const boxRef = ref()

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
    steps: [], // 过程流水，不进下次 history
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
        assistant.steps.push(`开始: ${label}`)
      } else if (evt.type === 'tool_end') {
        const label = evt.label || evt.name || '工具'
        assistant.status = `${label}完成`
        assistant.steps.push(`完成: ${label}`)
        if (evt.preview) {
          assistant.steps.push(`输出结果: ${evt.preview}`)
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
    // 这一轮什么都没产出（网络断了，或后端第一条就是 error）就把空气泡收掉，
    // 免得对话里留一个空白框。有 steps 的留着——那是这轮真实发生过的过程。
    if (!assistant.content && !assistant.steps?.length) {
      messages.value.splice(assistantIndex, 1)
    }
    scrollToBottom()
  }
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

.chat-box {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 12px 4px;
  background-color: var(--app-bg-page);
  border-radius: var(--app-radius-md);
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
.bubble-steps {
  margin-bottom: 8px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--app-text-secondary);
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
