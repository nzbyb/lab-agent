import request from '@/utils/request'

export function getAnnouncementPageListApi(params) {
  return request({
    url: '/api/announcement/list',
    method: 'get',
    params
  })
}

export function getAnnouncementApi(id, params) {
  return request({
    url: `/api/announcement/${id}`,
    method: 'get',
    params
  })
}

export function createAnnouncementApi(data) {
  return request({
    url: '/api/announcement',
    method: 'post',
    data
  })
}

export function updateAnnouncementApi(id, data) {
  return request({
    url: `/api/announcement/${id}`,
    method: 'put',
    data
  })
}

export function deleteAnnouncementApi(id) {
  return request({
    url: `/api/announcement/${id}`,
    method: 'delete'
  })
}
