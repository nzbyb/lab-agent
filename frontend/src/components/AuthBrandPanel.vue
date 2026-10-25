<template>
  <!-- 登录 / 注册页左侧的品牌区。两页共用这一份，
       免得"改了登录页忘了改注册页"——那样两页并排看就成了两个系统。 -->
  <div class="brand-panel">
    <div class="brand-inner">
      <div class="brand-mark">
        <img src="@/assets/imgs/logo.svg" alt="智能实验室预约系统" />
      </div>
      <h1 class="brand-title">智能实验室预约系统</h1>
      <p class="brand-subtitle">FastAPI + Vue 3 · AI Agent 驱动的实验室预约与管理平台</p>
      <ul class="brand-features">
        <li>
          <el-icon><Calendar /></el-icon>
          <span>在线预约实验室与设备，各时段空闲情况一目了然</span>
        </li>
        <li>
          <el-icon><MagicStick /></el-icon>
          <span>AI 智能助手对话式预约，自动查数据、代提交</span>
        </li>
        <li>
          <el-icon><Reading /></el-icon>
          <span>知识库问答，预约规则与安全规范随手可查</span>
        </li>
        <li>
          <el-icon><DocumentChecked /></el-icon>
          <span>预约审核与账号、设备管理，管理员统一处理</span>
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup>
import { Calendar, MagicStick, Reading, DocumentChecked } from '@element-plus/icons-vue'
</script>

<style scoped>
/* ---------------------------------------------------------------------------
 * 左：品牌区
 *
 * 渐变终点取主色 --el-color-primary（#2563eb），让这块和登录后各页面的主色
 * 是同一个蓝，不是另起一套配色。起点压到近黑的深蓝，和登录后的深色侧栏呼应。
 * ------------------------------------------------------------------------- */
.brand-panel {
  position: relative;
  overflow: hidden;
  flex: 1 1 55%;
  display: flex;
  align-items: center;
  /* 右边多留 140px，比下面的渐隐带（120px）宽：把内容挡在渐隐带之外。
   * 少了这 20px 余量，文字右端会飘到正在变白的区域上，白字白底直接消失。 */
  padding: 60px 140px 60px 60px;
  color: #fff;
  /* 第一层（写在前面 = 画在上面）把右边缘 120px 从全透明渐变到纯白，
   * 第二层才是深蓝渐变。叠加结果是深蓝自己溶进白色里——两栏之间不再有
   * 那条硬边。 */
  background-image:
    linear-gradient(90deg, rgba(255, 255, 255, 0) calc(100% - 120px), #ffffff 100%),
    linear-gradient(135deg, #0f172a 0%, #1e3a8a 55%, #2563eb 100%);
}

/* 左下的两个浅色圆弧，纯装饰 */
.brand-panel::before,
.brand-panel::after {
  content: '';
  position: absolute;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.07);
  pointer-events: none;
}

.brand-panel::before {
  width: 460px;
  height: 460px;
  right: -140px;
  bottom: -200px;
}

.brand-panel::after {
  width: 280px;
  height: 280px;
  right: 60px;
  bottom: -210px;
}

.brand-inner {
  position: relative; /* 压在装饰圆弧之上 */
  z-index: 1;
  width: 100%;
  max-width: 460px;
  margin: 0 auto;
}

.brand-mark {
  width: 84px;
  height: 84px;
  /* 图标自身是圆角透明的，box-shadow 会照方形元素画出一圈直角阴影，
   * drop-shadow 才是跟着图标轮廓走的。 */
  filter: drop-shadow(0 10px 24px rgba(0, 0, 0, 0.18));
}

.brand-mark img {
  width: 100%;
  height: 100%;
  display: block;
}

/* 字号随视口自适应，不是"为了好看"，是为了修一条断点缝。
 *
 * 断点在 900px（下面的媒体查询只管 max-width: 900px），所以 901px 起仍是左右分栏。
 * 左栏占 55% 宽、左右内边距 60+140=200px，于是 .brand-inner 的可用宽度是
 * "55% × 视口 − 200"：901px 时只有 295.6px，一直到 936px 也才涨到 314.8px。
 * 而标题"智能实验室预约系统"9 个字在 34px 下的实宽是
 *   9 × 34px（字身） + 9 × 1px（letter-spacing）= 315px
 * ——字距 9px 不能漏，漏了会算成 306px，结论就偏了。
 * 315px 要放得下来，视口得到 937px（55%×937−200 = 315.4）。
 * 也就是说 901~936px 这一整段都放不下，标题被硬折成两行。
 * 用 clamp 让它在这段里缩到 24px 出头就放得下了（24px 时实宽仅 225px）。
 *
 * 1440px 时 2.6vw = 37.4px，被上限卡回 34px，观感与改造后完全一致。
 * 900px 以下由文件末尾的媒体查询接管（那里显式写 22px，在后、同权重，会盖过这条）。 */
.brand-title {
  font-size: clamp(24px, 2.6vw, 34px);
  font-weight: 600;
  line-height: 1.3;
  letter-spacing: 1px;
}

.brand-subtitle {
  margin-top: 12px;
  font-size: 14px;
  line-height: 1.7;
  color: rgba(255, 255, 255, 0.8);
}

.brand-features {
  margin-top: 30px;
}

.brand-features li {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 0;
  font-size: 15px;
  color: rgba(255, 255, 255, 0.92);
  border-bottom: 1px solid rgba(255, 255, 255, 0.15);
}

.brand-features li:last-child {
  border-bottom: none;
}

/* 图标默认跟着 li 的 15px，比正文还轻；单给到 18px。
 * flex: none 是不让它被右侧长文案挤扁（li 本身是 flex 容器）。 */
.brand-features li .el-icon {
  flex: none;
  font-size: 18px;
}

/* ---------------------------------------------------------------------------
 * 窄屏：品牌区从左侧栏变成顶部横幅，只留 logo + 标题。
 * 那 4 条特性在手机上会把登录框挤出首屏，隐藏。
 * ------------------------------------------------------------------------- */
@media (max-width: 900px) {
  .brand-panel {
    flex: none;
    /* 竖排后交界线是横的，渐隐带跟着转到底部 */
    padding: 32px 24px 90px;
    background-image:
      linear-gradient(180deg, rgba(255, 255, 255, 0) calc(100% - 80px), #ffffff 100%),
      linear-gradient(135deg, #0f172a 0%, #1e3a8a 55%, #2563eb 100%);
  }

  .brand-inner {
    max-width: none;
  }

  .brand-mark {
    width: 56px;
    height: 56px;
  }

  .brand-title {
    margin-top: 16px;
    font-size: 22px;
  }

  .brand-subtitle,
  .brand-features {
    display: none;
  }
}
</style>
