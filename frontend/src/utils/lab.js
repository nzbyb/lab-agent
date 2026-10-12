// 实验室「开不开」这件事，界面上要说准。
//
// 三件容易混的事，后端 LabResponse 里是三个独立字段：
//   status                     管理员有没有启用这间实验室（0 停用 / 1 启用）
//   today_open_time/close_time 今天生效的时段，两个都是空 = 今天不开放（比如周末）
//   open_now                   此刻在不在时段内
// 所以「管理员启用了」不等于「此刻开着」——一间启用着的实验室，晚上照样是关门的。
//
// 三个值全部由后端算好（lab_service.to_lab_response）。前端**不要**自己拿
// new Date() 去比时段：一旦两边各算各的，就会出现"列表说开着、下单说关了"，
// 而"某一天该用哪套时段"（周中还是周末）这套规则的唯一判断点在后端。

/**
 * 卡片/横幅上那颗状态标签该显示什么。
 * 返回 { text, type }，type 直接用 el-tag 的类型。
 */
export const labOpenState = (lab) => {
  if (!lab || lab.status !== 1) {
    // 停用优先于时间：停用的实验室，不管几点都是"不能去"，
    // 这时候显示"今日不开放"会把原因说错，用户会以为是时间问题。
    return { text: '已停用', type: 'info' }
  }
  if (!lab.today_open_time || !lab.today_close_time) {
    return { text: '今日不开放', type: 'info' }
  }
  return lab.open_now ? { text: '开放中', type: 'success' } : { text: '已闭馆', type: 'warning' }
}

/** 今天生效的时段，形如 "08:00 - 20:00"；今天不开放时返回空串。 */
export const todayHoursText = (lab) => {
  if (!lab || !lab.today_open_time || !lab.today_close_time) return ''
  return `${lab.today_open_time} - ${lab.today_close_time}`
}

/** 周中时段（管理端表格里要跟周末并排显示，所以单独给一个）。 */
export const weekdayHoursText = (lab) => {
  if (!lab || !lab.open_time || !lab.close_time) return ''
  return `${lab.open_time} - ${lab.close_time}`
}

/** 周末时段；周末不开放时返回空串。 */
export const weekendHoursText = (lab) => {
  if (!lab || !lab.weekend_open_time || !lab.weekend_close_time) return ''
  return `${lab.weekend_open_time} - ${lab.weekend_close_time}`
}
