import request from '@/utils/request'

export function getUserInfoApi() {
  return request({
    url: '/api/user/me',
    method: 'get'
  })
}

export function updateUserInfoApi(data) {
  return request({
    url: '/api/user/me',
    method: 'put',
    data
  })
}

// 本人改密码：要带原密码，改完自己会被踢下线。
export function updatePasswordApi(data) {
  return request({
    url: '/api/user/password',
    method: 'put',
    data
  })
}

// 管理员重置**别人**的密码：不带原密码（管理员本来也不知道），
// 重置完被重置的那个人所有设备立刻掉线。
export function resetUserPasswordApi(userId, data) {
  return request({
    url: `/api/user/${userId}/password`,
    method: 'put',
    data
  })
}

export function getUserPageListApi(params) {
  return request({
    url: '/api/user/list',
    method: 'get',
    params
  })
}

export function createUserApi(data) {
  return request({
    url: '/api/user',
    method: 'post',
    data
  })
}

export function updateUserApi(userId, data) {
  return request({
    url: `/api/user/${userId}`,
    method: 'put',
    data
  })
}

export function deleteUserApi(userId) {
  return request({
    url: `/api/user/${userId}`,
    method: 'delete'
  })
}
