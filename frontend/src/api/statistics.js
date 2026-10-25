import request from '@/utils/request'

export function getStatisticsOverviewApi() {
  return request({
    url: '/api/statistics/overview',
    method: 'get'
  })
}

export function getAdminWorkbenchApi() {
  return request({
    url: '/api/statistics/admin-workbench',
    method: 'get'
  })
}
