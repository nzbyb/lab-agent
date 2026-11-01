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

/**
 * 导出预约报表。
 *
 * responseType: 'blob' 之后响应拦截器会走单独一条分支：正常情况把整个响应交给
 * 调用方（要读 Content-Disposition 里的文件名），出错时后端返回的是 JSON 而不是文件，
 * 拦截器会解析出来弹提示并 reject。见 utils/request.js。
 */
export function exportReservationsApi(params) {
  return request({
    url: '/api/statistics/export/reservations',
    method: 'get',
    params,
    responseType: 'blob'
  })
}
