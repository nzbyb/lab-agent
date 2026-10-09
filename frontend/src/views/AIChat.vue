<template>
  <div>
    <el-card>
      <template #header>
        <div style="font-size: 16px; font-weight: bold">
          <span>AI智能助手</span>
        </div>
      </template>
      <div
        ref="boxRef"
        style="
          height: 480px;
          overflow-y: auto;
          padding: 8px 4px;
          background-color: #fafafa;
          border-radius: 6px;
        "
      >
        <div
          v-for="(item, index) in messages"
          :key="index"
          :style="{
            display: 'flex',
            justifyContent: item.role === 'user' ? 'flex-end' : 'flex-start',
            marginBottom: '12px'
          }"
        >
          <div
            class="bubble"
            :style="{
              maxWidth: '70%',
              padding: '10px 12px',
              borderRadius: '8px',
              backgroundColor: item.role === 'user' ? '#409eff' : '#fff',
              color: item.role === 'user' ? '#fff' : '#333',
              whiteSpace: 'pre-wrap',
              lineHeight: '1.6',
              boxShadow: '0 1px 2px rgba(0, 0, 0, 0.06)'
            }"
          >
            <!-- 当前进行中的一句话，如「正在查询开放实验室...」 -->
            <div
              v-if="item.role === 'assistant' && item.status"
              style="margin-bottom: 6px; font-size: 12px; color: #909399"
            >
              {{ item.status }}
            </div>
            <!-- 本轮已发生的过程列表，只展示不回传给后端 -->
            <div
              v-if="item.role === 'assistant' && item.steps?.length"
              style="margin-bottom: 8px; font-size: 12px; color: #909399; line-height: 1.5"
            >
              <div v-for="(step, i) in item.steps" :key="i">• {{ step }}</div>
            </div>
            <div v-html="parseMarkdown(item.content)"></div>
          </div>
        </div>
      </div>
      <div style="margin-top: 12px; display: flex; gap: 8px; align-items: flex-end">
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
        <el-button type="primary" @click="handleSend" :loading="loading">发送</el-button>
      </div>
    </el-card>
  </div>
</template>
<script setup>
import { chatStreamApi } from '@/api/ai'
import { ref, reactive, nextTick } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { ElMessage } from 'element-plus'
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

const scrollToBottom = () => {
  nextTick(() => {
    const elem = boxRef.value
    if (elem) elem.scrollTop = elem.scrollHeight
  })
}

const handleSend = async () => {
  const text = input.value.trim()
  if (!text || loading.value) return

  messages.value.push({ role: 'user', content: text })
  input.value = ''
  loading.value = true
  scrollToBottom()

  // 必须用 reactive: 普通对象 push 后再改字段，视图可能不更新
  const assistant = reactive({
    role: 'assistant',
    content: '', // 正文：靠 token 一点点拼
    status: '正在思考...', // 当前状态文案
    steps: [] // 过程流水，不进下次 history
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
    // 只保留 role/content; status、steps 丢掉
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
.bubble :deep(p) {
  margin: 0;
}
.bubble :deep(p + p) {
  margin-top: 6px;
}
.bubble :deep(ul),
.bubble :deep(ol) {
  margin: 0;
  padding-left: 20px;
}
</style>
