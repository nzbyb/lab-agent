/**
 * ECharts 按需引入。
 *
 * 用 `echarts/core` + 显式 `echarts.use([...])`，而不是 `import * as echarts from 'echarts'`：
 * 全量包好几百 KB，首页只用两张最基础的图，不值得为它拖慢首屏。
 *
 * ⚠️ 按需引入的经典坑：**漏注册某个组件不会报错，图会是全白的**。
 * 比如用了 tooltip 却没注册 TooltipComponent，控制台一声不响，图上就是没有浮层；
 * 漏了 CanvasRenderer 则整个容器一片空白。所以以后新增图表类型时，
 * **必须回到这个文件同步补注册**——症状是"页面正常、控制台干净、图全白"，
 * 很难往"注册表"上想。
 *
 * 目前注册的是首页实际用到的部分：
 * - LineChart / BarChart —— 近 7 天预约趋势、实验室预约排行
 * - GridComponent —— 直角坐标系（折线、柱状都建在它上面）
 * - TooltipComponent —— 鼠标悬停浮层
 * - CanvasRenderer —— 渲染器，缺了容器全白
 */
import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, CanvasRenderer])

export default echarts
