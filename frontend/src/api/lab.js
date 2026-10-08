import request from '@/utils/request'

export function getLabPageListApi(params) {
  return request({
    url: '/api/lab/list',
    method: 'get',
    params
  })
}

/**
 * @param {Number} lab_id
 * @returns
 */
export function getLab(lab_id) {
  return request({
    url: `/api/lab/${lab_id}`,
    method: 'get'
  })
}

export function createLabApi(data) {
  return request({
    url: '/api/lab',
    method: 'post',
    data
  })
}

export function updateLabApi(labId, data) {
  return request({
    url: `/api/lab/${labId}`,
    method: 'put',
    data
  })
}

export function deleteLabApi(labId) {
  return request({
    url: `/api/lab/${labId}`,
    method: 'delete'
  })
}


