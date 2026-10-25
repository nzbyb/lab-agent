import request from '@/utils/request'

export function getNotificationPageListApi(params) {
  return request({
    url: '/api/notification/list',
    method: 'get',
    params
  })
}

export function getUnreadCountApi() {
  return request({
    url: '/api/notification/unread-count',
    method: 'get'
  })
}

export function markNotificationReadApi(id) {
  return request({
    url: `/api/notification/${id}/read`,
    method: 'put'
  })
}

export function markAllNotificationsReadApi() {
  return request({
    url: '/api/notification/read-all',
    method: 'put'
  })
}
