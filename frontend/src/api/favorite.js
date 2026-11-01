import request from '@/utils/request'

export function getFavoriteIdsApi() {
  return request({
    url: '/api/favorite/ids',
    method: 'get'
  })
}

export function getFavoriteListApi() {
  return request({
    url: '/api/favorite/list',
    method: 'get'
  })
}

export function getRecentViewsApi(params) {
  return request({
    url: '/api/favorite/recent',
    method: 'get',
    params
  })
}

export function addFavoriteApi(labId) {
  return request({
    url: `/api/favorite/${labId}`,
    method: 'post'
  })
}

export function removeFavoriteApi(labId) {
  return request({
    url: `/api/favorite/${labId}`,
    method: 'delete'
  })
}

export function recordLabViewApi(labId) {
  return request({
    url: `/api/favorite/${labId}/view`,
    method: 'post'
  })
}
