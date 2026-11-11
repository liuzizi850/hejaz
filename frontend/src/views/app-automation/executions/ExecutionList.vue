<template>
  <div class="execution-list">
    <!-- 工具栏 -->
    <el-card class="toolbar" shadow="never">
      <el-row :gutter="20">
        <el-col :span="4">
          <el-select v-model="projectFilter" :placeholder="$t('appAutomation.execution.allProjects')" clearable filterable @change="loadExecutions">
            <el-option v-for="p in projectList" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-col>
        <el-col :span="8">
          <el-input
            v-model="searchQuery"
            :placeholder="$t('appAutomation.execution.searchPlaceholder')"
            clearable
            @clear="loadExecutions"
            @keyup.enter="loadExecutions"
          >
            <template #prefix>
              <el-icon><Search /></el-icon>
            </template>
          </el-input>
        </el-col>
        <el-col :span="12" class="text-right">
          <el-select
            v-model="statusFilter"
            :placeholder="$t('appAutomation.execution.statusFilter')"
            clearable
            style="width: 150px; margin-right: 10px"
            @change="loadExecutions"
          >
            <el-option :label="$t('appAutomation.common.all')" value="" />
            <el-option :label="$t('appAutomation.status.pending')" value="pending" />
            <el-option :label="$t('appAutomation.status.running')" value="running" />
            <el-option :label="$t('appAutomation.status.completed')" value="completed" />
            <el-option :label="$t('appAutomation.status.error')" value="error" />
            <el-option :label="$t('appAutomation.status.stopped')" value="stopped" />
          </el-select>
          <el-button :disabled="!selectedRows.length || batching || deleting" @click="batchDownload">批量下载</el-button>
          <el-button :disabled="!selectedRows.length || batching || deleting" @click="batchExport">批量导出</el-button>
          <el-button type="danger" plain :disabled="!selectedRows.length || batching || deleting" @click="batchRemoveExecutions">批量删除</el-button>
          <el-button @click="loadExecutions">
            <el-icon><Refresh /></el-icon>
            {{ $t('appAutomation.common.refresh') }}
          </el-button>
        </el-col>
      </el-row>
    </el-card>
    
    <!-- 执行记录列表 -->
    <el-card class="table-card" shadow="never">
      <el-table
        v-loading="loading"
        :data="executions"
        stripe
        row-key="id"
        style="width: 100%"
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="48" />
        <el-table-column prop="case_name" :label="$t('appAutomation.execution.testCase')" min-width="180" />
        <el-table-column prop="device_name" :label="$t('appAutomation.execution.device')" width="150" />
        <el-table-column :label="$t('appAutomation.common.status')" width="100">
          <template #default="{ row }">
            <el-tag :type="getDisplayStatus(row.status, row.result).type" size="small">
              {{ getDisplayStatus(row.status, row.result).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="$t('appAutomation.execution.progress')" width="150">
          <template #default="{ row }">
            <el-progress
              :percentage="row.progress || 0"
              :status="row.status === 'error' ? 'exception' : row.result === 'failed' ? 'exception' : row.result === 'passed' ? 'success' : undefined"
            />
          </template>
        </el-table-column>
        <el-table-column :label="$t('appAutomation.execution.stepStats')" width="180">
          <template #default="{ row }">
            <div class="step-stats">
              <span class="stat-item success">{{ $t('appAutomation.status.passed') }}: {{ row.passed_steps || 0 }}</span>
              <span class="stat-item danger">{{ $t('appAutomation.status.failed') }}: {{ row.failed_steps || 0 }}</span>
              <span class="stat-item">{{ $t('appAutomation.execution.total') }}: {{ row.total_steps || 0 }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="$t('appAutomation.execution.duration')" width="100">
          <template #default="{ row }">
            {{ formatDuration(row.duration) }}
          </template>
        </el-table-column>
        <el-table-column prop="user_name" :label="$t('appAutomation.execution.executor')" width="100" />
        <el-table-column :label="$t('appAutomation.execution.startTime')" width="160">
          <template #default="{ row }">
            {{ formatDateTime(row.started_at) }}
          </template>
        </el-table-column>
        <el-table-column :label="$t('appAutomation.execution.endTime')" width="160">
          <template #default="{ row }">
            {{ row.finished_at ? formatDateTime(row.finished_at) : '-' }}
          </template>
        </el-table-column>
        <el-table-column :label="$t('appAutomation.common.operation')" width="300" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'running'"
              type="warning"
              size="small"
              text
              @click="stopExecution(row)"
            >
              {{ $t('appAutomation.common.stop') }}
            </el-button>
            <el-button
              v-if="row.report_path || row.result_bundle_path"
              type="primary"
              size="small"
              text
              @click="viewReport(row)"
            >
              {{ $t('appAutomation.execution.viewReport') }}
            </el-button>
            <el-button
              v-if="row.error_message || row.mismatch_current_url || row.mismatch_expected_url"
              type="danger"
              size="small"
              text
              @click="viewError(row)"
            >
              {{ $t('appAutomation.execution.viewError') }}
            </el-button>
            <a
              v-if="row.result_bundle_path"
              class="bundle-download"
              :href="bundleMediaUrl(row.result_bundle_path)"
              download
            >
              下载
            </a>
            <el-button
              v-if="row.status !== 'running' && row.status !== 'pending'"
              type="danger"
              size="small"
              text
              :disabled="deleting"
              @click="removeExecution(row)"
            >
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      
      <!-- 分页 -->
      <div class="pagination">
        <el-pagination
          v-model:current-page="currentPage"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="loadExecutions"
          @current-change="loadExecutions"
        />
      </div>
    </el-card>
    
    <!-- 错误信息对话框 -->
    <el-dialog
      v-model="errorDialogVisible"
      :title="$t('appAutomation.execution.errorInfo')"
      width="600px"
    >
      <div class="error-content">
        <div v-if="mismatchCurrentUrl || mismatchExpectedUrl" class="mismatch-shots">
          <div v-if="mismatchCurrentUrl">
            <p>当前界面</p>
            <img :src="mismatchCurrentUrl" alt="当前界面" />
          </div>
          <div v-if="mismatchExpectedUrl">
            <p>开始界面</p>
            <img :src="mismatchExpectedUrl" alt="开始界面" />
          </div>
        </div>
        <pre v-if="currentError">{{ currentError }}</pre>
      </div>
      <template #footer>
        <el-button type="primary" @click="errorDialogVisible = false">
          {{ $t('appAutomation.common.close') }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="reportDialogVisible" title="执行结果" width="860px">
      <video v-if="reportVideo" class="report-video" :src="reportVideo" controls></video>
      <el-table v-if="reportSteps.length" :data="reportSteps" max-height="420">
        <el-table-column prop="order" label="顺序" width="70" />
        <el-table-column prop="name" label="操作" min-width="180" />
        <el-table-column label="结果" width="80">
          <template #default="{ row }">{{ stepStatusText(row.status) }}</template>
        </el-table-column>
        <el-table-column label="截图" width="140">
          <template #default="{ row }">
            <img v-if="row.screenshot_url" class="report-shot" :src="row.screenshot_url" alt="" />
          </template>
        </el-table-column>
        <el-table-column prop="reason" label="说明" min-width="120" />
      </el-table>
      <template #footer>
        <a v-if="reportDownload" class="report-download" :href="reportDownload" download>下载压缩包</a>
        <el-button type="primary" @click="reportDialogVisible = false">{{ $t('appAutomation.common.close') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getExecutionList,
  getExecutionBundle,
  batchDownloadExecutions,
  batchExportExecutions,
  deleteExecution,
  batchDeleteExecutions,
  saveBlobResponse,
  stopExecution as apiStopExecution,
  getAppProjects
} from '@/api/app-automation'
import { Search, Refresh } from '@element-plus/icons-vue'
import { getExecutionStatusType, getExecutionStatusText, getDisplayStatus, formatDateTime } from '@/utils/app-automation-helpers'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const loading = ref(false)
const executions = ref([])
const searchQuery = ref('')
const statusFilter = ref('')
const projectFilter = ref(null)
const projectList = ref([])
const currentPage = ref(1)
const pageSize = ref(20)
const total = ref(0)
const selectedRows = ref([])
const batching = ref(false)
const deleting = ref(false)

const onSelectionChange = (rows) => {
  selectedRows.value = rows
}

const runBatch = async (request, fallbackName) => {
  if (!selectedRows.value.length) {
    ElMessage.warning('请选择执行记录')
    return
  }
  batching.value = true
  try {
    const response = await request(selectedRows.value.map(row => row.id))
    await saveBlobResponse(response, fallbackName)
  } catch (error) {
    ElMessage.error(error.message || '导出失败')
  } finally {
    batching.value = false
  }
}

const batchDownload = () => runBatch(batchDownloadExecutions, '执行报告.zip')
const batchExport = () => runBatch(batchExportExecutions, '执行报告.xlsx')

const removeExecution = async (row) => {
  try {
    await ElMessageBox.confirm('确定删除这条执行记录吗？删除后不能恢复。', '删除', { type: 'warning' })
  } catch {
    return
  }
  deleting.value = true
  try {
    await deleteExecution(row.id)
    ElMessage.success('已删除')
    selectedRows.value = selectedRows.value.filter(item => item.id !== row.id)
    await loadExecutions()
  } catch (error) {
    ElMessage.error(error.response?.data?.message || error.message || '删除失败')
  } finally {
    deleting.value = false
  }
}

const batchRemoveExecutions = async () => {
  if (!selectedRows.value.length) {
    ElMessage.warning('请选择执行记录')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确定删除选中的 ${selectedRows.value.length} 条执行记录吗？删除后不能恢复。`,
      '批量删除',
      { type: 'warning' }
    )
  } catch {
    return
  }
  deleting.value = true
  try {
    await batchDeleteExecutions(selectedRows.value.map(row => row.id))
    ElMessage.success('已删除')
    selectedRows.value = []
    await loadExecutions()
  } catch (error) {
    ElMessage.error(error.response?.data?.message || error.message || '删除失败')
  } finally {
    deleting.value = false
  }
}

const errorDialogVisible = ref(false)
const currentError = ref('')
const mismatchCurrentUrl = ref('')
const mismatchExpectedUrl = ref('')

let refreshTimer = null

const loadExecutions = async () => {
  loading.value = true
  try {
    const params = {
      page: currentPage.value,
      page_size: pageSize.value,
      search: searchQuery.value,
      status: statusFilter.value
    }
    if (projectFilter.value) params.project = projectFilter.value
    const res = await getExecutionList(params)
    executions.value = res.data.results || []
    total.value = res.data.count || 0
  } catch (error) {
    ElMessage.error(t('appAutomation.execution.loadFailed') + ': ' + (error.message || t('appAutomation.execution.unknownError')))
  } finally {
    loading.value = false
  }
}

const stopExecution = async (execution) => {
  try {
    await ElMessageBox.confirm(
      t('appAutomation.execution.stopConfirm'),
      t('appAutomation.execution.confirmStop'),
      {
        confirmButtonText: t('appAutomation.common.confirm'),
        cancelButtonText: t('appAutomation.common.cancel'),
        type: 'warning'
      }
    )
    
    const res = await apiStopExecution(execution.id)
    if (res.data.success) {
      ElMessage.success(t('appAutomation.execution.executionStopped'))
      loadExecutions()
    }
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(t('appAutomation.execution.stopFailed') + ': ' + (error.message || t('appAutomation.execution.unknownError')))
    }
  }
}

const reportDialogVisible = ref(false)
const reportSteps = ref([])
const reportVideo = ref('')
const reportDownload = ref('')

const stepStatusText = (status) => {
  if (status === 'passed') return '通过'
  if (status === 'failed') return '失败'
  return status || ''
}

const viewReport = async (execution) => {
  if (!execution || !execution.id) {
    ElMessage.warning(t('appAutomation.execution.invalidExecutionId'))
    return
  }
  if (execution.result_bundle_path) {
    try {
      const res = await getExecutionBundle(execution.id)
      reportSteps.value = res.data.steps || []
      reportVideo.value = res.data.video_url || ''
      reportDownload.value = res.data.download_url || ''
      reportDialogVisible.value = true
      return
    } catch (error) {
      ElMessage.error('报告打不开')
      return
    }
  }
  window.open(`/api/app-automation/executions/${execution.id}/report/`, '_blank')
}

const viewError = (execution) => {
  currentError.value = execution.error_message || ''
  mismatchCurrentUrl.value = execution.mismatch_current_url || ''
  mismatchExpectedUrl.value = execution.mismatch_expected_url || ''
  errorDialogVisible.value = true
}

const bundleMediaUrl = (filePath) => {
  if (!filePath) return ''
  const normalized = String(filePath).replace(/\\/g, '/')
  const marker = '/media/'
  const index = normalized.toLowerCase().lastIndexOf(marker)
  if (index >= 0) return normalized.slice(index)
  const trimmed = normalized.replace(/^\/+/, '')
  if (trimmed.toLowerCase().startsWith('media/')) return `/${trimmed}`
  return `/media/${trimmed}`
}

// getDisplayStatus 已从 helpers 导入

const formatDuration = (seconds) => {
  if (!seconds) return '-'
  if (seconds < 60) return t('appAutomation.execution.durationSeconds', { n: Math.floor(seconds) })
  const minutes = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return t('appAutomation.execution.durationMinutesSeconds', { m: minutes, s: secs })
}

// 自动刷新执行中的记录
const startAutoRefresh = () => {
  refreshTimer = setInterval(() => {
    // 如果有执行中的记录，自动刷新
    const hasRunning = executions.value.some(e => ['running', 'pending'].includes(e.status))
    if (hasRunning) {
      loadExecutions()
    }
  }, 5000) // 每5秒刷新一次
}

const stopAutoRefresh = () => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

onMounted(() => {
  getAppProjects({ page_size: 100 }).then(res => { projectList.value = res.data.results || res.data || [] }).catch(() => {})
  loadExecutions()
  startAutoRefresh()
})

onUnmounted(() => {
  stopAutoRefresh()
})
</script>

<style scoped lang="scss">
.execution-list {
  padding: 20px;
}

.toolbar {
  margin-bottom: 20px;
  
  .text-right {
    text-align: right;
  }
}

.table-card {
  .pagination {
    margin-top: 20px;
    display: flex;
    justify-content: flex-end;
  }
}

.step-stats {
  display: flex;
  gap: 8px;
  font-size: 12px;
  
  .stat-item {
    &.success { color: #67c23a; }
    &.danger { color: #f56c6c; }
  }
}

.error-content {
  max-height: 400px;
  overflow-y: auto;

  .mismatch-shots {
    display: flex;
    gap: 12px;
    margin-bottom: 12px;

    p {
      margin: 0 0 8px;
    }

    img {
      max-width: 100%;
      max-height: 220px;
      object-fit: contain;
      background: #f5f7fa;
    }
  }
  
  pre {
    background: #f5f7fa;
    padding: 15px;
    border-radius: 4px;
    font-family: 'Courier New', Courier, monospace;
    font-size: 13px;
    line-height: 1.5;
    white-space: pre-wrap;
    word-wrap: break-word;
  }
}

.report-video {
  width: 100%;
  max-height: 240px;
  margin-bottom: 12px;
  background: #000;
}

.report-shot {
  width: 96px;
  height: 64px;
  object-fit: cover;
  background: #f5f7fa;
}

.bundle-download,
.report-download {
  margin-right: 12px;
  color: #409eff;
}
</style>
