<template>
  <div class="ai-run-page">
    <el-card shadow="never">
      <template #header>
        <div class="page-header">
          <span class="title">{{ $t('appAutomation.aiRun.title') }}</span>
          <span class="subtitle">{{ $t('appAutomation.aiRun.subtitle') }}</span>
        </div>
      </template>

      <el-row :gutter="20">
        <el-col :span="14">
          <div class="section-title">{{ $t('appAutomation.aiRun.scriptsTitle') }}</div>
          <div class="section-actions">
            <el-upload
              :show-file-list="false"
              accept=".feature"
              :http-request="handleUpload"
            >
              <el-button type="primary" plain :loading="uploading">{{ $t('appAutomation.aiRun.upload') }}</el-button>
            </el-upload>
            <el-button @click="loadScripts" :loading="scriptsLoading">{{ $t('appAutomation.aiRun.refreshScripts') }}</el-button>
          </div>
          <el-checkbox-group v-model="selectedScriptIds" class="script-list">
            <el-checkbox
              v-for="script in scripts"
              :key="script.id"
              :label="script.id"
              :value="script.id"
            >
              <span class="script-name">{{ script.name }}</span>
              <el-tag size="small" type="info" class="script-tag">{{ sourceLabel(script.source) }}</el-tag>
            </el-checkbox>
          </el-checkbox-group>
          <div v-if="!scriptsLoading && scripts.length === 0" class="hint">
            {{ $t('appAutomation.aiRun.noScripts') }}
          </div>
        </el-col>
        <el-col :span="10">
          <div class="section-title">{{ $t('appAutomation.aiRun.devicesTitle') }}</div>
          <div class="section-actions">
            <el-button @click="loadDevices" :loading="devicesLoading">{{ $t('appAutomation.aiRun.refreshDevices') }}</el-button>
          </div>
          <el-radio-group v-model="selectedSerial" class="device-list" v-if="devices.length">
            <el-radio
              v-for="device in devices"
              :key="device.serial"
              :label="device.serial"
              :value="device.serial"
            >
              {{ device.name || device.serial }}
            </el-radio>
          </el-radio-group>
          <el-alert
            v-if="!devicesLoading && devices.length === 0"
            type="warning"
            :closable="false"
            :title="deviceMessage || $t('appAutomation.aiRun.noDevices')"
          />
        </el-col>
      </el-row>

      <div class="run-actions">
        <el-button
          type="primary"
          size="large"
          :disabled="!canStart"
          :loading="starting"
          @click="startRun"
        >
          {{ $t('appAutomation.aiRun.start') }}
        </el-button>
      </div>
    </el-card>

    <el-card shadow="never" class="result-card" v-if="currentRun || runError">
      <template #header>
        <div class="page-header">
          <span class="title">{{ $t('appAutomation.aiRun.resultTitle') }}</span>
          <div class="result-actions" v-if="currentRun">
            <el-tag :type="statusTagType(currentRun.status)">{{ statusLabel(currentRun.status) }}</el-tag>
            <el-button
              v-if="currentRun.report_available"
              type="primary"
              plain
              @click="downloadZip"
              :loading="downloading"
            >
              {{ $t('appAutomation.aiRun.download') }}
            </el-button>
            <el-button
              v-if="currentRun.report_available"
              @click="copyShareLink"
              :loading="sharing"
            >
              {{ $t('appAutomation.aiRun.copyShare') }}
            </el-button>
          </div>
        </div>
      </template>

      <el-alert v-if="runError" type="error" :closable="false" :title="runError" class="mb" />
      <p v-if="currentRun && isActive(currentRun.status)" class="hint">
        {{ $t('appAutomation.aiRun.runningHint') }}
      </p>
      <p v-if="currentRun && currentRun.error_message" class="hint error-text">
        {{ currentRun.error_message }}
      </p>

      <div v-if="currentRun && currentRun.cases && currentRun.cases.length" class="cases">
        <el-card
          v-for="item in currentRun.cases"
          :key="item.id"
          shadow="never"
          class="case-card"
          :class="item.status"
        >
          <div class="case-header">
            <strong>{{ item.id }} · {{ item.name }}</strong>
            <el-tag size="small" :type="item.status === 'pass' ? 'success' : 'danger'">
              {{ item.status === 'pass' ? $t('appAutomation.aiRun.passed') : $t('appAutomation.aiRun.failed') }}
            </el-tag>
          </div>
          <p v-if="item.status !== 'pass'" class="failure-reason">
            {{ $t('appAutomation.aiRun.failureReason') }}：{{ item.failure_reason || '—' }}
          </p>
          <div class="shots" v-if="item.screenshots && item.screenshots.length">
            <img v-for="(src, idx) in item.screenshots" :key="idx" :src="src" :alt="item.id" />
          </div>
        </el-card>
      </div>

      <iframe
        v-if="currentRun && currentRun.report_html_url && currentRun.report_available"
        class="report-frame"
        :src="currentRun.report_html_url"
        :title="$t('appAutomation.aiRun.reportFrame')"
      />
    </el-card>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import {
  listAiRunScripts,
  uploadAiRunScript,
  listAiRunDevices,
  createAiRun,
  getAiRun,
  downloadAiRunZip,
  createAiRunShare
} from '@/api/app-automation'

const { t } = useI18n()

const scripts = ref([])
const scriptsLoading = ref(false)
const uploading = ref(false)
const selectedScriptIds = ref([])

const devices = ref([])
const devicesLoading = ref(false)
const deviceMessage = ref('')
const selectedSerial = ref('')

const starting = ref(false)
const downloading = ref(false)
const sharing = ref(false)
const currentRun = ref(null)
const runError = ref('')
let pollTimer = null

const canStart = computed(() => {
  return selectedScriptIds.value.length > 0 && !!selectedSerial.value && !starting.value
})

const sourceLabel = (source) => {
  return source === 'upload' ? t('appAutomation.aiRun.sourceUpload') : t('appAutomation.aiRun.sourceBuiltin')
}

const isActive = (status) => status === 'pending' || status === 'running'

const statusLabel = (status) => {
  const map = {
    pending: t('appAutomation.aiRun.statusPending'),
    running: t('appAutomation.aiRun.statusRunning'),
    completed: t('appAutomation.aiRun.statusCompleted'),
    success: t('appAutomation.aiRun.statusCompleted'),
    failed: t('appAutomation.aiRun.statusFailed')
  }
  return map[status] || status
}

const statusTagType = (status) => {
  if (status === 'completed' || status === 'success') return 'success'
  if (status === 'failed') return 'danger'
  return 'warning'
}

const loadScripts = async () => {
  scriptsLoading.value = true
  try {
    const res = await listAiRunScripts()
    scripts.value = res.scripts || res.data?.scripts || []
  } catch (error) {
    ElMessage.error(error?.message || t('appAutomation.aiRun.loadFailed'))
  } finally {
    scriptsLoading.value = false
  }
}

const loadDevices = async () => {
  devicesLoading.value = true
  try {
    const res = await listAiRunDevices()
    devices.value = res.devices || res.data?.devices || []
    deviceMessage.value = res.message || res.data?.message || ''
    if (!devices.value.some((item) => item.serial === selectedSerial.value)) {
      selectedSerial.value = devices.value[0]?.serial || ''
    }
  } catch (error) {
    devices.value = []
    deviceMessage.value = error?.message || t('appAutomation.aiRun.noDevices')
  } finally {
    devicesLoading.value = false
  }
}

const handleUpload = async (option) => {
  uploading.value = true
  try {
    const res = await uploadAiRunScript(option.file)
    const script = res.script || res.data?.script
    ElMessage.success(t('appAutomation.aiRun.uploadSuccess'))
    await loadScripts()
    if (script?.id && !selectedScriptIds.value.includes(script.id)) {
      selectedScriptIds.value = [...selectedScriptIds.value, script.id]
    }
  } catch (error) {
    ElMessage.error(error?.message || t('appAutomation.aiRun.uploadFailed'))
  } finally {
    uploading.value = false
  }
}

const startRun = async () => {
  starting.value = true
  runError.value = ''
  currentRun.value = null
  try {
    const res = await createAiRun({
      serial: selectedSerial.value,
      script_ids: selectedScriptIds.value
    })
    currentRun.value = res.run || res.data?.run
    startPolling()
  } catch (error) {
    const message = error?.message || t('appAutomation.aiRun.startFailed')
    runError.value = message
    ElMessage.error(message)
  } finally {
    starting.value = false
  }
}

const startPolling = () => {
  stopPolling()
  pollTimer = setInterval(refreshRun, 2000)
  refreshRun()
}

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const refreshRun = async () => {
  if (!currentRun.value?.id) return
  try {
    const res = await getAiRun(currentRun.value.id)
    currentRun.value = res.run || res.data?.run
    if (currentRun.value && !isActive(currentRun.value.status)) {
      stopPolling()
    }
  } catch (error) {
    stopPolling()
    runError.value = error?.message || t('appAutomation.aiRun.loadFailed')
  }
}

const downloadZip = async () => {
  if (!currentRun.value?.id) return
  downloading.value = true
  try {
    const blob = await downloadAiRunZip(currentRun.value.id)
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `ai-run-${currentRun.value.id}.zip`
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  } catch (error) {
    ElMessage.error(error?.message || t('appAutomation.aiRun.downloadFailed'))
  } finally {
    downloading.value = false
  }
}

const copyShareLink = async () => {
  if (!currentRun.value?.id) return
  sharing.value = true
  try {
    const res = await createAiRunShare(currentRun.value.id)
    const share = res.share || res.data?.share
    const path = share?.url || `/ai-run-share/${share?.token}`
    const full = `${window.location.origin}${path}`
    await navigator.clipboard.writeText(full)
    ElMessage.success(t('appAutomation.aiRun.shareCopied'))
  } catch (error) {
    ElMessage.error(error?.message || t('appAutomation.aiRun.shareFailed'))
  } finally {
    sharing.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadScripts(), loadDevices()])
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<style scoped lang="scss">
.ai-run-page {
  padding: 20px;
}

.page-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;

  .title {
    font-size: 18px;
    font-weight: 600;
    color: #303133;
  }

  .subtitle {
    color: #909399;
    font-size: 13px;
  }
}

.section-title {
  font-weight: 600;
  margin-bottom: 8px;
}

.section-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.script-list,
.device-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}

.script-name {
  margin-right: 8px;
}

.script-tag {
  margin-left: 4px;
}

.hint {
  color: #909399;
  font-size: 13px;
}

.error-text {
  color: #f56c6c;
}

.run-actions {
  margin-top: 24px;
}

.result-card {
  margin-top: 20px;
}

.result-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.mb {
  margin-bottom: 12px;
}

.case-card {
  margin-bottom: 12px;

  &.fail {
    border-left: 3px solid #f56c6c;
  }

  &.pass {
    border-left: 3px solid #67c23a;
  }
}

.case-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.failure-reason {
  color: #f56c6c;
  margin: 0 0 8px;
}

.shots {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;

  img {
    max-width: 240px;
    max-height: 180px;
    border: 1px solid #ebeef5;
    border-radius: 4px;
  }
}

.report-frame {
  width: 100%;
  min-height: 480px;
  border: 1px solid #ebeef5;
  margin-top: 16px;
  background: #fff;
}
</style>
