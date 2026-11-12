<template>
  <div class="record-session">
    <el-card shadow="never">
      <div class="toolbar">
        <el-select
          v-model="deviceId"
          class="device-select"
          filterable
          placeholder="选择设备"
          :disabled="!!sessionId"
          :loading="devicesLoading"
        >
          <el-option
            v-for="device in devices"
            :key="device.device_id"
            :label="deviceLabel(device)"
            :value="device.device_id"
          />
        </el-select>
        <el-button
          type="primary"
          :disabled="!deviceId || !!sessionId"
          :loading="starting"
          @click="startRecording"
        >
          录制
        </el-button>
        <el-button
          v-if="isRecording"
          :loading="treeLoading"
          @click="openAssertion"
        >
          标为断言
        </el-button>
        <el-button
          v-if="isRecording"
          type="warning"
          :loading="stopping"
          @click="stopRecording"
        >
          停止
        </el-button>
        <el-button
          v-if="isRecording"
          :loading="interrupting"
          @click="interruptRecording"
        >
          中断
        </el-button>
      </div>

      <p v-if="isRecording" class="hint">
        正在录制。手机上的点击、滑动和输入会在停止或中断后出现在步骤表里。
      </p>

      <div v-if="canEdit" class="save-bar">
        <el-input v-model="caseName" class="case-name" placeholder="用例名" />
        <el-button @click="appendWait">添加等待</el-button>
        <el-button type="primary" :loading="saving" @click="saveCase">保存</el-button>
      </div>

      <el-alert
        v-if="passwordHint"
        class="password-alert"
        type="warning"
        :closable="false"
        show-icon
        :title="passwordHint"
      />

      <el-table
        v-if="sessionId"
        class="step-table"
        :data="steps"
        stripe
        empty-text="还没有步骤"
      >
        <el-table-column prop="order" label="顺序" width="80" />
        <el-table-column prop="name" label="名称" min-width="180" />
        <el-table-column label="类型" width="120">
          <template #default="{ row }">
            {{ typeLabel(row.type) }}
          </template>
        </el-table-column>
        <el-table-column v-if="hasEmptyPasswords" label="密码" min-width="180">
          <template #default="{ row }">
            <el-input
              v-if="row._needsPassword"
              v-model="row.input_text"
              placeholder="补上密码"
            />
          </template>
        </el-table-column>
        <el-table-column v-if="canEdit" label="操作" width="220" fixed="right">
          <template #default="{ $index }">
            <el-button text size="small" :disabled="$index === 0" @click="moveStep($index, -1)">上移</el-button>
            <el-button text size="small" :disabled="$index === steps.length - 1" @click="moveStep($index, 1)">下移</el-button>
            <el-button text size="small" type="danger" @click="removeStep($index)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="assertionVisible" title="标为断言" width="560px">
      <div v-loading="treeLoading">
        <div class="section-title">界面文字</div>
        <el-checkbox-group v-if="screenTexts.length" v-model="checkedTextIndexes" class="checkbox-list">
          <el-checkbox v-for="(text, index) in screenTexts" :key="`${text}-${index}`" :value="index">
            {{ text }}
          </el-checkbox>
        </el-checkbox-group>
        <p v-else class="hint">当前界面没有可勾选的文字</p>

        <div class="section-title">控件</div>
        <el-checkbox-group v-if="screenSelectors.length" v-model="checkedSelectorIndexes" class="checkbox-list">
          <el-checkbox v-for="(selector, index) in screenSelectors" :key="index" :value="index">
            {{ selectorLabel(selector) }}
          </el-checkbox>
        </el-checkbox-group>
        <p v-else class="hint">当前界面没有可勾选的控件</p>

        <div class="section-title">其他期望文字</div>
        <div v-for="(text, index) in extraTexts" :key="index" class="extra-row">
          <el-input v-model="extraTexts[index]" placeholder="期望出现的文字" />
          <el-button v-if="extraTexts.length > 1" text @click="extraTexts.splice(index, 1)">删除</el-button>
        </div>
        <el-button text @click="extraTexts.push('')">添加输入框</el-button>
      </div>
      <template #footer>
        <el-button @click="assertionVisible = false">取消</el-button>
        <el-button type="primary" :loading="asserting" @click="submitAssertion">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  createRecordingSession,
  getAppDevices,
  getRecordingScreenTree,
  interruptRecordingSession,
  postRecordingAssertion,
  saveRecordingSession,
  stopRecordingSession
} from '@/api/app-automation'

const router = useRouter()

const TYPE_LABELS = {
  click: '点击',
  long_press: '长按',
  swipe: '滑动',
  input: '输入',
  assert: '断言',
  wait: '等待'
}

const devices = ref([])
const devicesLoading = ref(false)
const deviceId = ref('')
const sessionId = ref(null)
const sessionStatus = ref('')
const steps = ref([])
const caseName = ref('')
const savedCaseId = ref(null)
const passwordHint = ref('')

const starting = ref(false)
const stopping = ref(false)
const interrupting = ref(false)
const saving = ref(false)
const asserting = ref(false)

const assertionVisible = ref(false)
const treeLoading = ref(false)
const screenTexts = ref([])
const screenSelectors = ref([])
const checkedTextIndexes = ref([])
const checkedSelectorIndexes = ref([])
const extraTexts = ref([''])

const isRecording = computed(() => sessionStatus.value === 'recording')
const canEdit = computed(() => sessionStatus.value === 'stopped' || sessionStatus.value === 'interrupted')
const hasEmptyPasswords = computed(() => steps.value.some((step) => step._needsPassword))

const deviceLabel = (device) => {
  if (device.name && device.name !== device.device_id) {
    return `${device.name} (${device.device_id})`
  }
  return device.device_id
}

const typeLabel = (type) => TYPE_LABELS[type] || type || ''

const selectorLabel = (selector) => {
  return selector.text || selector.content_desc || selector.resource_id || selector.class_name || '控件'
}

const apiMessage = (error, fallback) => error?.response?.data?.message || fallback

const reindexSteps = () => {
  steps.value.forEach((step, index) => {
    step.order = index + 1
  })
}

const replaceSteps = (incoming) => {
  steps.value = (incoming || []).map((step, index) => ({
    ...step,
    order: index + 1
  }))
}

const loadDevices = async () => {
  devicesLoading.value = true
  try {
    const res = await getAppDevices({ page: 1, page_size: 1000 })
    const data = res.data
    devices.value = Array.isArray(data) ? data : (data.results || [])
  } catch (error) {
    ElMessage.error(apiMessage(error, '设备列表加载失败'))
  } finally {
    devicesLoading.value = false
  }
}

const startRecording = async () => {
  if (!deviceId.value || sessionId.value) return
  starting.value = true
  try {
    const res = await createRecordingSession({ device_id: deviceId.value })
    sessionId.value = res.data.id
    sessionStatus.value = res.data.status || 'recording'
    steps.value = []
    passwordHint.value = ''
    ElMessage.success('开始录制')
  } catch (error) {
    ElMessage.error(apiMessage(error, '录制失败'))
  } finally {
    starting.value = false
  }
}

const openAssertion = async () => {
  assertionVisible.value = true
  screenTexts.value = []
  screenSelectors.value = []
  checkedTextIndexes.value = []
  checkedSelectorIndexes.value = []
  extraTexts.value = ['']
  treeLoading.value = true
  try {
    const res = await getRecordingScreenTree(sessionId.value)
    screenTexts.value = res.data.texts || []
    screenSelectors.value = (res.data.selectors || []).filter(
      (selector) => selector.text || selector.resource_id || selector.content_desc
    )
  } catch (error) {
    ElMessage.error(apiMessage(error, '抓不到当前界面'))
  } finally {
    treeLoading.value = false
  }
}

const submitAssertion = async () => {
  const expectedTexts = [
    ...checkedTextIndexes.value.map((index) => screenTexts.value[index]).filter(Boolean),
    ...extraTexts.value.map((text) => (text || '').trim()).filter(Boolean)
  ]
  const expectedSelectors = checkedSelectorIndexes.value
    .map((index) => screenSelectors.value[index])
    .filter(Boolean)
  if (!expectedTexts.length && !expectedSelectors.length) {
    ElMessage.warning('请勾选要校验的文字或控件')
    return
  }
  asserting.value = true
  try {
    const res = await postRecordingAssertion(sessionId.value, {
      expected_texts: expectedTexts,
      expected_selectors: expectedSelectors
    })
    steps.value = [...steps.value, res.data]
    assertionVisible.value = false
    ElMessage.success('已添加断言')
  } catch (error) {
    ElMessage.error(apiMessage(error, '添加断言失败'))
  } finally {
    asserting.value = false
  }
}

const finishRecording = (status, incomingSteps) => {
  sessionStatus.value = status
  replaceSteps(incomingSteps)
}

const stopRecording = async () => {
  stopping.value = true
  try {
    const res = await stopRecordingSession(sessionId.value)
    finishRecording('stopped', res.data.steps)
  } catch (error) {
    ElMessage.error(apiMessage(error, '停止失败'))
  } finally {
    stopping.value = false
  }
}

const interruptRecording = async () => {
  interrupting.value = true
  try {
    const res = await interruptRecordingSession(sessionId.value)
    finishRecording('interrupted', res.data.steps)
    ElMessage.success('录制已中断，步骤已保留')
  } catch (error) {
    ElMessage.error(apiMessage(error, '中断失败'))
  } finally {
    interrupting.value = false
  }
}

const moveStep = (index, offset) => {
  const target = index + offset
  if (target < 0 || target >= steps.value.length) return
  const [item] = steps.value.splice(index, 1)
  steps.value.splice(target, 0, item)
  reindexSteps()
}

const removeStep = (index) => {
  steps.value.splice(index, 1)
  reindexSteps()
}

const appendWait = () => {
  steps.value.push({
    type: 'wait',
    duration_ms: 1000,
    name: '等待',
    platform: 'android',
    order: steps.value.length + 1
  })
}

const stepsForSave = () => {
  return steps.value.map((step, index) => {
    const copy = { ...step, order: index + 1 }
    delete copy._needsPassword
    return copy
  })
}

const saveCase = async () => {
  saving.value = true
  try {
    const payload = {
      name: caseName.value,
      steps: stepsForSave()
    }
    if (savedCaseId.value != null) {
      payload.case_id = savedCaseId.value
    }
    const res = await saveRecordingSession(sessionId.value, payload)
    if (res.data?.id != null) {
      savedCaseId.value = res.data.id
    }
    const empty = res.data?.empty_password_steps || []
    if (empty.length) {
      const emptySet = new Set(empty)
      steps.value.forEach((step) => {
        step._needsPassword = emptySet.has(step.order)
      })
      passwordHint.value = `请补上这些步骤的密码：${empty.join('、')}`
      ElMessage.warning(passwordHint.value)
      return
    }
    passwordHint.value = ''
    sessionStatus.value = 'saved'
    ElMessage.success('保存成功')
    router.push('/app-automation/test-cases')
  } catch (error) {
    ElMessage.error(apiMessage(error, '保存失败'))
  } finally {
    saving.value = false
  }
}

onMounted(loadDevices)

onBeforeUnmount(() => {
  if (sessionStatus.value === 'recording' && sessionId.value) {
    interruptRecordingSession(sessionId.value).catch(() => {})
  }
})
</script>

<style scoped lang="scss">
.record-session {
  padding: 20px;
}

.toolbar,
.save-bar,
.extra-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.device-select,
.case-name {
  width: 280px;
}

.save-bar,
.password-alert,
.step-table {
  margin-top: 16px;
}

.hint {
  margin: 12px 0 0;
  color: #909399;
  font-size: 13px;
}

.section-title {
  margin: 12px 0 8px;
  font-weight: 600;
}

.checkbox-list {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  max-height: 220px;
  overflow: auto;
}

.extra-row {
  margin-bottom: 8px;
}

.extra-row .el-input {
  flex: 1;
}
</style>
