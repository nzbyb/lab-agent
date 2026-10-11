import request from '@/utils/request'

export function getStatisticsOverviewApi() {
  return request({
    url: '/api/statistics/overview',
    method: 'get'
  })
}
