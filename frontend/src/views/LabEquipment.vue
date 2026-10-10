<template>
  <div>
    <el-card>
      <template #header>
        <div style="display: flex; justify-content: space-between; align-items: center">
          <div class="app-card-title">
            <span>{{ lab?.name || '实验室' }}设备列表 </span>
          </div>
          <div>
            <!-- 和 LabList.vue 的「预约」按钮保持一致：关闭中的实验室不该能打开预约弹窗。
                 入口 LabList 的「查看设备」没有 status 判断，所以这里必须自己挡一道，
                 否则用户点得动、一路填完，最后才被后端「实验室未开放预约」拒掉。 -->
            <el-button type="primary" :disabled="lab?.status !== 1" @click="handleReserveLab"
              >预约实验室
            </el-button>
            <el-button @click="router.push('/manager/lab-list')">返回实验室列表 </el-button>
          </div>
        </div>
      </template>
      <div
        v-if="lab"
        style="
          color: #666;
          margin-bottom: 16px;
          background-color: #f4f5ff;
          padding: 10px;
          border-radius: 6px;
        "
      >
        <!-- 把实验室状态显式标出来。上面两个预约按钮在实验室关闭时会全部置灰，
             不给原因的话用户只会看到一排点不动的按钮，以为是页面坏了。
             标签用词和配色跟 Lab.vue 的实验室列表保持一致（开启/关闭 + success/danger）。 -->
        <div style="margin-bottom: 10px">
          <el-tag
            :type="lab.status === 1 ? 'success' : 'danger'"
            size="small"
            style="margin-right: 8px"
          >
            {{ lab.status === 1 ? '开启' : '关闭' }}
          </el-tag>
          简介: {{ lab.description }}
        </div>
        <div>
          位置: {{ lab.location }} <span style="margin: 0 10px">|</span> 容纳 {{ lab.capacity }} 人
          <span style="margin: 0 10px">|</span>
          开放时间:
          {{ lab.open_time && lab.close_time ? `${lab.open_time} - ${lab.close_time}` : '-' }}
        </div>
      </div>

      <el-table :data="tableData" style="width: 100%" v-loading="loading">
        <el-table-column prop="img" label="图片" width="100">
          <template #default="{ row }">
            <div style="min-height: 50px; display: flex; align-items: center">
              <el-image
                v-if="row.img"
                style="display: block; width: 50px; height: 50px; border-radius: 6px"
                :src="row.img"
                :preview-src-list="[row.img]"
                :preview-teleported="true"
                alt=""
              />
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="设备名称" />
        <el-table-column prop="spec" label="型号规格" />
        <el-table-column prop="quantity" label="数量" width="80" />
        <el-table-column prop="status" label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : 'danger'">
              {{ row.status === 1 ? '正常' : '维修' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="100">
          <template #default="{ row }">
            <!-- 除设备自身状态外还要看实验室状态。后端 reservation_service.create_reservation
                 是先判 lab.status 再判设备的，所以实验室关闭时这里放行也没用——用户能一路
                 填完表单，最后才被「实验室未开放预约」拒掉。lab 拉取失败时为 null，
                 lab?.status !== 1 得到 true → 保持禁用（fail-closed）。 -->
            <el-button
              :disabled="!row.status || lab?.status !== 1"
              type="primary"
              text
              bg
              @click="handleReserveEquipment(row)"
              >预约</el-button
            >
          </template>
        </el-table-column>
      </el-table>
      <div class="app-pagination">
        <el-pagination
          v-model:current-page="params.page"
          v-model:page-size="params.page_size"
          :total="total"
          background
          layout="prev, pager, next, total"
          @current-change="loadEquipment"
        />
      </div>
    </el-card>
    <reserve-dialog
      v-model:visible="reserveVisible"
      :lab-id="lab?.id"
      :lab-name="lab?.name"
      :equipment-id="currentEquipment?.id"
      :equipment-name="currentEquipment?.name"
    ></reserve-dialog>
  </div>
</template>
<script setup>
import { getLab } from '@/api/lab'
import { ElMessage } from 'element-plus'
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getEquipmentPageListApi } from '@/api/equipment'
import ReserveDialog from '@/components/ReserveDialog.vue'

const route = useRoute()
const router = useRouter()

const reserveVisible = ref(false)
const lab = ref(null)
const currentEquipment = ref(null)
const params = {
  page: 1,
  page_size: 10,
  lab_id: Number(route.query.lab_id)
}

const loading = ref(false)
const tableData = ref([])
const total = ref(0)

// 打开弹窗前重新确认一次实验室状态。
// lab 是挂载时那份快照（onMounted 里只拉一次），用户停留本页期间管理员把实验室
// 禁用了，按钮上的禁用条件读到的仍是旧值 1，照样放行——又回到「填完才被拒」。
// 这里补一次实时校验，把窗口压到「这次 fetch 到用户点确定」之间的毫秒级；
// 最终把关的仍然是后端 create_reservation 里的 lab.status 判断。
const ensureLabOpen = async () => {
  // lab_id 缺失时 loadLab 自己会提示，这里静默拦下，免得弹两条 toast
  if (!params.lab_id) return false
  // 确认不了状态时一律静默返回 false，不再补 toast。request.js 的响应拦截器已经弹过了：
  // code!==200 弹后端的 message，无响应弹「网络异常」，HTTP 401 直接跳登录。
  // 这里再弹一条只会盖住后端给的真正原因——后端说「实验室不存在」，
  // 本页却提示「请刷新后重试」，会把用户往「网络抖动」上引偏。
  let fresh = null
  try {
    fresh = await loadLab()
  } catch {
    return false // fail-closed：拦截器已提示过
  }
  if (!fresh) return false
  if (fresh.status !== 1) {
    ElMessage.warning('该实验室已关闭，暂不可预约')
    return false
  }
  return true
}

const handleReserveLab = async () => {
  if (!(await ensureLabOpen())) return
  currentEquipment.value = null
  reserveVisible.value = true
}
const handleReserveEquipment = async (equipment) => {
  if (!(await ensureLabOpen())) return
  currentEquipment.value = equipment
  reserveVisible.value = true
}

// 返回本次拉到的实验室；拉取失败返回 null，让调用方能把「旧快照」当「拿不到」处理。
const loadLab = async () => {
  if (!params.lab_id) {
    ElMessage.error('缺少实验室查询条件 [lab_id]')
    return null
  }
  const res = await getLab(params.lab_id)
  if (res.code === 200) {
    lab.value = res.data
    return res.data
  }
  return null
}

const loadEquipment = async () => {
  loading.value = true
  try {
    const res = await getEquipmentPageListApi(params)
    if (res.code === 200) {
      tableData.value = res.data?.list
      total.value = res.data?.total
    }
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadLab()
  loadEquipment()
})
</script>
