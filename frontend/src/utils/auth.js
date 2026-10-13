const TOKEN_KEY = 'token'
const USER_KEY = 'userInfo'

// AI 助手「上次聊到哪」那条记录的键名前缀，完整键名是前缀 + 用户 id
// （读写点见 views/AIChat.vue 的 storageKey / persist）。
//
// 前缀放这个文件，是因为登出时要按它清理，而登出和另外两个键的读写都在这里。
// 键名按用户 id 分名，所以换个人登录读不到上一个人的会话；但登出时**仍要主动删**——
// 共用一台电脑时，下一个人打开开发者工具就能看到上一位的会话标识。
// （后端每条读取都按 user_id 过滤，所以漏出去的只是标识，不是聊天正文。）
export const AI_LAST_CONVERSATION_PREFIX = 'ai_last_conversation:'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token)
}

export function removeToken() {
  localStorage.removeItem(TOKEN_KEY)
}

export function getUserInfo() {
  const str = localStorage.getItem(USER_KEY)
  return str ? JSON.parse(str) : null
}

export function setUserInfo(userInfo) {
  localStorage.setItem(USER_KEY, JSON.stringify(userInfo))
}

export function removeUserInfo() {
  localStorage.removeItem(USER_KEY)
}

export function logout() {
  removeToken()
  removeUserInfo()
  // 上一次聊到哪条会话也留着，但它是按用户 id 分名的，不清的话会一直躺在
  // 这个浏览器里（同一台电脑换过几个账号就积几条）。localStorage 没有按前缀
  // 删的 API，只能遍历；顺手把所有用户的记录都清掉，不留隔夜账。
  Object.keys(localStorage)
    .filter((key) => key.startsWith(AI_LAST_CONVERSATION_PREFIX))
    .forEach((key) => localStorage.removeItem(key))
}
