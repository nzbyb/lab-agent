import request from '@/utils/request'

export function getAuditLogPageListApi(params) {
  return request({
    url: '/api/audit/list',
    method: 'get',
    params
  })
}
