import request from '@/utils/request'

export function loginApi(data) {
  return request({
    url: '/api/auth/login',
    method: 'post',
    data
  })
}

export function logoutApi() {
  return request({
    url: '/api/auth/logout',
    method: 'post'
  })
}

export function loginByPhoneApi(data) {
  return request({
    url: '/api/auth/login/phone',
    method: 'post',
    data
  })
}

export function sendEmailCodeApi(data) {
  return request({
    url: '/api/auth/email-code',
    method: 'post',
    data
  })
}

export function loginByEmailCodeApi(data) {
  return request({
    url: '/api/auth/login/email-code',
    method: 'post',
    data
  })
}

export function sendRegisterCodeApi(data) {
  return request({
    url: '/api/auth/register/email-code',
    method: 'post',
    data
  })
}

export function registerApi(data) {
  return request({
    url: '/api/auth/register',
    method: 'post',
    data
  })
}

export function sendResetCodeApi(data) {
  return request({
    url: '/api/auth/password/email-code',
    method: 'post',
    data
  })
}

export function resetPasswordApi(data) {
  return request({
    url: '/api/auth/password/reset',
    method: 'post',
    data
  })
}
