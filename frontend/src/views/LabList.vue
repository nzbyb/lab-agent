<template>
  <div>
    <el-card>
      <template #header>
        <div class="app-card-title">
          <span>实验室列表</span>
        </div>
      </template>
      <div class="app-search-bar">
        <el-input
          placeholder="请输入账号或名称查询"
          v-model="params.keywords"
          class="app-search-input"
          clearable
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        ></el-input>
        <el-button type="primary" :icon="Search" @click="handleSearch">查询</el-button>
      </div>
      <div>
        <el-row :gutter="16" v-loading="loading">
          <el-col v-for="item in tableData" :key="item.id" :span="6" style="margin-bottom: 16px">
            <el-card shadow="hover">
              <img
                v-if="item.img"
                :src="item.img"
                alt=""
                style="
                  display: block;
                  width: 100%;
                  height: 150px;
                  object-fit: cover;
                  border-radius: 6px;
                "
              />
              <div
                v-else
                style="width: 100%; height: 150px; background-color: #f5f7fa; border-radius: 6px"
              ></div>
              <div class="app-card-title" style="margin-top: 10px">
                {{ item.name }}
              </div>
              <!-- 把状态显式标出来。下面的「预约」按钮在实验室关闭时会置灰，
                   不给原因的话用户只看到一颗点不动的按钮，以为是页面坏了。
                   用词和配色对齐 Lab.vue 列表页与 LabEquipment.vue 详情页（开启/关闭 + success/danger）。 -->
              <div style="margin-top: 8px">
                <el-tag :type="item.status === 1 ? 'success' : 'danger'" size="small">
                  {{ item.status === 1 ? '开启' : '关闭' }}
                </el-tag>
              </div>
              <div style="font-size: 13px; margin-top: 8px; color: #666">
                位置：{{ item.location || '-' }}
              </div>
              <div style="font-size: 13px; margin-top: 6px; color: #666">
                容量：{{ item.capacity }} 人
              </div>
              <div style="font-size: 13px; margin-top: 6px; color: #666">
                开放时间：{{
                  item.open_time && item.close_time ? `${item.open_time} - ${item.close_time}` : '-'
                }}
              </div>
              <div style="margin-top: 12px; display: flex; gap: 8px">
                <el-button style="flex: 1" @click="handleViewEquipment(item)">查看设备</el-button>
                <el-button
                  style="flex: 1"
                  type="primary"
                  :disabled="item.status !== 1"
                  @click="handleReserve(item)"
                  >预约</el-button
                >
              </div>
            </el-card>
          </el-col>
        </el-row>
        <div class="app-pagination">
          <el-pagination
            v-model:current-page="params.page"
            v-model:page-size="params.page_size"
            :total="total"
            background
            layout="prev, pager, next, total"
            @current-change="load"
          />
        </div>
      </div>
    </el-card>

    <reserve-dialog
      v-model:visible="reserveVisible"
      :lab-id="currentLab?.id"
      :lab-name="currentLab?.name"
    ></reserve-dialog>
  </div>
</template>
<script setup>
import { ref, reactive, onMounted } from 'vue'
import { getLab, getLabPageListApi } from '@/api/lab'
import { Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import router from '@/router'
import ReserveDialog from '@/components/ReserveDialog.vue'

const reserveVisible = ref(false)
const currentLab = ref(null)
const params = reactive({
  page: 1,
  page_size: 10,
  keywords: ''
})
const loading = ref(false)
const tableData = ref([])
const total = ref(0)

const handleViewEquipment = (lab) => {
  router.push({ path: '/manager/lab-equipment', query: { lab_id: lab.id } })
}

// 打开弹窗前重新确认一次实验室状态。
// 列表数据是挂载/搜索/翻页时拉的快照，用户停留本页期间管理员把实验室关掉时，
// 按钮上的 :disabled 读到的仍是旧值 1、照样放行——又回到「填完才被后端拒掉」。
// 这里补一次实时校验，把窗口压到「这次 fetch 到用户点确定」之间的毫秒级；
// 最终把关的仍然是后端 create_reservation 里的 lab.status 判断。
const ensureLabOpen = async (lab) => {
  if (!lab?.id) return false
  let res = null
  try {
    res = await getLab(lab.id)
  } catch {
    return false // fail-closed：request.js 的拦截器已经提示过了
  }
  // code !== 200 时拦截器已弹 toast 且**不 reject**，这里只取数据，不再补第二条提示
  if (res?.code !== 200) return false
  if (res.data?.status !== 1) {
    ElMessage.warning('该实验室已关闭，暂不可预约')
    return false
  }
  return true
}

const handleReserve = async (lab) => {
  if (!(await ensureLabOpen(lab))) return
  currentLab.value = lab
  reserveVisible.value = true
}

const load = async () => {
  loading.value = true
  try {
    const res = await getLabPageListApi(params)
    if (res.code === 200) {
      tableData.value = res.data?.list
      total.value = res.data?.total
    }
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  params.page = 1
  load()
}

onMounted(() => {
  load()
})
</script>
