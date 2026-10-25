<template>
  <div>
    <el-dialog
      :model-value="visible"
      title="预约"
      width="min(820px, 94vw)"
      top="6vh"
      @open="handleOpen"
      @close="emit('update:visible', false)"
    >
      <!-- 先看一周的占用，再决定具体时段。点绿色格子会自动填下面的表单；
           手填表单仍然保留，想约半点的用户不用被网格限制。 -->
      <WeekSchedule
        v-if="visible && labId"
        :lab-id="labId"
        :equipment-id="equipmentId || null"
        @select="handleSelectSlot"
      />
      <div class="reserve-divider"><span>或手动选择时间</span></div>

      <el-form
        ref="formRef"
        :rules="rules"
        :model="form"
        label-width="80px"
        class="app-dialog-form"
      >
        <el-form-item label="实验室">
          <el-input :model-value="labName" disabled />
        </el-form-item>
        <el-form-item label="设备">
          <el-input :model-value="equipmentName" disabled />
        </el-form-item>
        <el-form-item label="预约日期" prop="date">
          <el-date-picker
            v-model="form.date"
            type="date"
            format="YYYY-MM-DD"
            value-format="YYYY-MM-DD"
            placeholder="请选择预约日期"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="开始时间" prop="start_time">
          <el-time-picker
            v-model="form.start_time"
            type="time"
            format="HH:mm"
            value-format="HH:mm"
            placeholder="请选择开始时间"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="结束时间" prop="end_time">
          <el-time-picker
            v-model="form.end_time"
            type="time"
            format="HH:mm"
            value-format="HH:mm"
            placeholder="请选择结束时间"
            style="width: 100%"
          />
        </el-form-item>
        <!-- 必须有 prop：Element Plus 的 resetFields() 只重置"注册过 prop"的
             FormItem（源码里 `if (props.prop) formContext?.addField(...)`）。
             少了它，上面 @open 那句 resetFields 清不掉备注，上一次填的内容会
             留着，并被下一次预约原样提交。 -->
        <el-form-item label="备注" prop="remark">
          <el-input type="textarea" v-model="form.remark" placeholder="请输入备注" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="emit('update:visible', false)">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>
<script setup>
import { ref, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { createReservationApi } from '@/api/reservation'
import WeekSchedule from '@/components/WeekSchedule.vue'
const props = defineProps({
  visible: Boolean,
  labId: Number,
  labName: String,
  equipmentId: Number,
  equipmentName: String
})
const submitting = ref(false)
const emit = defineEmits(['update:visible'])
const formRef = ref()
const form = reactive({
  date: '',
  start_time: '09:00',
  end_time: '18:00',
  remark: ''
})
const rules = {
  date: [{ required: true, message: '请选择预约日期', trigger: 'change' }],
  start_time: [{ required: true, message: '请选择开始时间', trigger: 'change' }],
  end_time: [{ required: true, message: '请选择结束时间', trigger: 'change' }]
}

const handleOpen = () => {
  formRef.value?.resetFields()
}

// 点网格里的空格：只负责把日期和时间填进表单，不直接提交。
// 用户还能补备注、改结束时间——直接提交等于绕过了表单校验和确认这一步。
const handleSelectSlot = (slot) => {
  form.date = slot.date
  form.start_time = slot.start_time
  form.end_time = slot.end_time
  ElMessage.success(`已选择 ${slot.date} ${slot.start_time}-${slot.end_time}`)
}

const handleSubmit = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    const res = await createReservationApi({
      lab_id: props.labId,
      equipment_id: props.equipmentId,
      date: form.date,
      start_time: form.start_time,
      end_time: form.end_time,
      remark: form.remark
    })
    if (res.code === 200) {
      ElMessage.success('预约已提交，请等待管理员审核')
      emit('update:visible', false)
    }
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
/* 一条细分隔线，把"从网格挑"和"手填表单"分开 */
.reserve-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 2px 0 16px;
  font-size: 12px;
  color: var(--app-text-placeholder);
}

.reserve-divider::before,
.reserve-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--app-border);
}
</style>
