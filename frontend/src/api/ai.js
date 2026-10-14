import { getToken } from '@/utils/auth'
import request from '@/utils/request'

export function chatApi(data) {
  return request({
    url: '/api/ai/chat',
    method: 'post',
    data,
    timeout: 30000
  })
}

export function listConversationsApi(params) {
  return request({
    url: '/api/chat/conversations',
    method: 'get',
    params
  })
}

// 会话已被保留上限删掉时，后端给的是 200 + data:null（不是报错），
// 调用方要判空，别直接当下标用。
export function getConversationMessagesApi(id) {
  return request({
    url: `/api/chat/conversations/${id}/messages`,
    method: 'get'
  })
}

export function deleteConversationApi(id) {
  return request({
    url: `/api/chat/conversations/${id}`,
    method: 'delete'
  })
}

export async function chatStreamApi(data, onEvent) {
  // 必须像 utils/request.js 那样兜底。开发时 .env.development 里有这个变量，所以看不出问题；
  // 但生产构建**不加载** .env.development，这里会变成 undefined，拼出
  // "undefined/api/ai/chat/stream"，整个 AI 流式对话直接失效。
  const baseUrl = import.meta.env.VITE_API_BASE_URL || ''
  const token = getToken()
  const res = await fetch(`${baseUrl}/api/ai/chat/stream`, {
    method: 'post',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      Authorization: `Bearer ${token}`
    },
    body: JSON.stringify(data)
  })
  if (res.status === 401) {
    // 这条走的是原生 fetch，**不经过 utils/request.js 的拦截器**，所以登出、跳转、
    // 提示都得调用方自己来。这里只负责把状态码和原因带出去（挂个 status 属性），
    // 交给 AIChat.vue 决定怎么办。
    let message = '登录已失效，请重新登录'
    try {
      const body = await res.json()
      if (body?.message) message = body.message
    } catch {
      // 后端 401 的响应体不是 JSON 时就用上面那句兜底，不要因为它把 401 变成别的错
    }
    const err = new Error(message)
    err.status = 401
    throw err
  }
  if (!res.ok || !res.body) {
    throw new Error('流式接口请求失败')
  }
  const contentType = res.headers.get('content-type')
  if (!contentType.includes('text/event-stream')) {
    throw new Error('流式接口返回异常')
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const chunks = buffer.split('\n\n')
    buffer = chunks.pop()
    for (const chunk of chunks) {
      const line = chunk
        .split('\n')
        .map((item) => item.trim())
        .find((item) => item.startsWith('data:'))
      if (!line) continue
      const res = line.slice(5).trim()
      if (!res || res === '[DONE]') continue
      try {
        onEvent(JSON.parse(res))
      } catch {}
    }
  }
}
