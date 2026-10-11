<template>
  <div ref="chartRef" :style="{ width: '100%', height }"></div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import echarts from '@/utils/echarts'

const props = defineProps({
  /** 完整的 ECharts option。父组件用 computed 派生，数据一变这里就重新 setOption。 */
  option: {
    type: Object,
    required: true
  },
  height: {
    type: String,
    default: '320px'
  }
})

const chartRef = ref(null)
// 用 shallowRef 而不是 ref：echarts 实例内部是一大坨又深又互相引用的对象，
// 套上 Vue 的深层响应式代理纯属白费性能（每次交互都要遍历），还可能引出难查的怪问题。
// 实例本身不需要被追踪，只需要在卸载时拿得到它去 dispose。
const chart = shallowRef(null)
let observer = null
let rafId = 0

onMounted(() => {
  chart.value = echarts.init(chartRef.value)
  // 第二参 notMerge=true：整体替换 option，不留上一次的 series。
  // 少了它，管理员切到学生再切回来时两条 series 会叠在同一张图上。
  chart.value.setOption(props.option, true)

  // 用**容器级** ResizeObserver，不是 window 的 resize 事件：
  // 侧边栏折叠会改这个容器的宽度，但那不会触发 window resize，
  // 用 window 监听的话图会一直保持旧宽度、右边留白或被裁掉。
  // 回调一帧内可能来好几次（拖拽缩放时），用 rAF 合并成一次真正的 resize。
  observer = new ResizeObserver(() => {
    cancelAnimationFrame(rafId)
    rafId = requestAnimationFrame(() => chart.value?.resize())
  })
  observer.observe(chartRef.value)
})

watch(
  () => props.option,
  (option) => {
    chart.value?.setOption(option, true)
  },
  // 父组件传的是 computed 的话，每次重算都是新对象，普通 watch 就够了。
  // 这里仍开 deep，是为了将来有人直接把 reactive 对象原地改掉时也不会图不变——
  // option 很小，深比较的代价可以忽略，而"图悄悄不更新"是更糟的失败方式。
  { deep: true }
)

onBeforeUnmount(() => {
  // 三件事都得做，漏一件都有后果：
  // 漏 disconnect → 已卸载的组件还在被回调，报错刷屏；
  // 漏 cancelAnimationFrame → 挂起的回调在实例 dispose 之后触发 resize，报错；
  // 漏 dispose → echarts 实例和 canvas 不释放，来回切页面就是一路泄漏。
  observer?.disconnect()
  observer = null
  cancelAnimationFrame(rafId)
  chart.value?.dispose()
  chart.value = null
})
</script>
