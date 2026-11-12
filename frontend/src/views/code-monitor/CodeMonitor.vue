<template>
  <div class="page-container">
    <div class="page-header">
      <h1 class="page-title">{{ pageTitle }}</h1>
      <div v-if="section === 'addresses'" class="header-actions">
        <el-button type="primary" @click="addressDialog = true">新增地址</el-button>
      </div>
    </div>

    <div class="card-container">
      <template v-if="section === 'addresses'">
        <el-table :data="addresses">
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="git_url" label="Git 地址" />
          <el-table-column prop="created_at" label="创建时间" />
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button link type="danger" @click="removeAddress(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </template>

      <template v-else-if="section === 'tasks'">
        <el-form label-width="100px">
          <el-form-item label="代码地址">
            <el-select v-model="form.addressId" clearable placeholder="选择已保存地址" :disabled="!!form.file" @change="form.file = null">
              <el-option v-for="item in addresses" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="上传 zip">
            <input type="file" accept=".zip" :disabled="!!form.addressId" @change="onFile" />
          </el-form-item>
          <el-form-item label="访问令牌">
            <el-input
              v-model="form.token"
              type="password"
              show-password
              placeholder="私有仓库填写，不会保存"
              @paste="onTokenPaste"
            />
            <span class="hint">{{ form.token.trim() ? `已填入 ${form.token.trim().length} 个字符` : '当前是空的，粘贴后应出现字数' }}</span>
          </el-form-item>
          <el-form-item label="模型">
            <el-select v-model="form.modelConfigId" placeholder="选择已启用模型">
              <el-option v-for="item in models" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="submitting" :disabled="models.length === 0 || !form.modelConfigId" @click="submitTask">开始扫描</el-button>
            <span v-if="submitting" class="hint">正在上传，压缩包较大时会等一会儿，完成后出现在下方扫描任务</span>
            <span v-else-if="models.length === 0" class="hint">没有已启用的模型配置</span>
          </el-form-item>
        </el-form>
        <el-table :data="tasks">
          <el-table-column prop="git_url" label="来源">
            <template #default="{ row }">{{ row.git_url || 'zip' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">{{ statusText[row.status] || row.status }}</template>
          </el-table-column>
          <el-table-column prop="progress" label="进度" width="80" />
          <el-table-column prop="error_message" label="失败原因" />
          <el-table-column prop="created_at" label="创建时间" />
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button link type="danger" @click="removeTask(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="pagination-container">
          <el-pagination
            v-model:current-page="taskPage.current"
            v-model:page-size="taskPage.size"
            :page-sizes="[10, 20, 50]"
            layout="total, sizes, prev, pager, next"
            :total="taskPage.total"
            @size-change="reloadTaskPage"
            @current-change="reloadTaskPage"
          />
        </div>
      </template>

      <template v-else-if="section === 'review-tasks'">
        <el-form label-width="100px">
          <el-form-item label="需求">
            <el-input
              v-model="reviewForm.requirement"
              type="textarea"
              :rows="6"
              :placeholder="reviewForm.requirementFile ? '已选择需求文件，这里可以留空' : '可以不填。用具体行为描述要检查的功能，或在下面上传需求文件'"
            />
          </el-form-item>
          <el-form-item label="需求文件">
            <input
              ref="requirementFileInput"
              type="file"
              accept=".txt,.md,.pdf,.docx"
              @change="onRequirementFile"
            />
            <el-button v-if="reviewForm.requirementFile" link type="primary" @click="clearRequirementFile">清除</el-button>
            <div class="hint requirement-hint">支持 txt、md、pdf、docx，文件不超过 10MB。上传了需求文件，需求就可以不写</div>
          </el-form-item>
          <el-form-item label="代码地址">
            <el-select v-model="reviewForm.addressId" clearable placeholder="选择已保存地址" :disabled="!!reviewForm.file" @change="reviewForm.file = null">
              <el-option v-for="item in addresses" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="上传 zip">
            <input type="file" accept=".zip" :disabled="!!reviewForm.addressId" @change="onReviewFile" />
          </el-form-item>
          <el-form-item label="访问令牌">
            <el-input
              v-model="reviewForm.token"
              type="password"
              show-password
              placeholder="私有仓库填写，不会保存"
              @paste="onReviewTokenPaste"
            />
            <span class="hint">{{ reviewForm.token.trim() ? `已填入 ${reviewForm.token.trim().length} 个字符` : '当前是空的，粘贴后应出现字数' }}</span>
          </el-form-item>
          <el-form-item label="模型">
            <el-select v-model="reviewForm.modelConfigId" placeholder="选择已启用模型">
              <el-option v-for="item in models" :key="item.id" :label="item.name" :value="item.id" />
            </el-select>
          </el-form-item>
          <el-form-item>
            <el-button
              type="primary"
              native-type="button"
              :loading="reviewSubmitting"
              :disabled="models.length === 0 || !reviewForm.modelConfigId"
              @click="submitReview"
            >开始检查</el-button>
            <span v-if="reviewSubmitting" class="hint">正在上传并读取需求，文件较大时会等一会儿，完成后出现在下方列表</span>
            <span v-else-if="models.length === 0" class="hint">没有已启用的模型配置</span>
            <span v-else-if="!reviewForm.modelConfigId" class="hint">请先选择模型</span>
            <span v-else class="hint">报告含测试优先级、补测用例和安全测试点</span>
          </el-form-item>
        </el-form>
        <el-table :data="reviewTasks">
          <el-table-column prop="requirement_text" label="需求" show-overflow-tooltip />
          <el-table-column prop="git_url" label="来源">
            <template #default="{ row }">{{ row.git_url || 'zip' }}</template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">{{ statusText[row.status] || row.status }}</template>
          </el-table-column>
          <el-table-column prop="progress" label="进度" width="80" />
          <el-table-column prop="error_message" label="失败原因" />
          <el-table-column prop="created_at" label="创建时间" />
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button link type="danger" @click="removeTask(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="pagination-container">
          <el-pagination
            v-model:current-page="reviewPage.current"
            v-model:page-size="reviewPage.size"
            :page-sizes="[10, 20, 50]"
            layout="total, sizes, prev, pager, next"
            :total="reviewPage.total"
            @size-change="reloadReviewPage"
            @current-change="reloadReviewPage"
          />
        </div>
      </template>

      <template v-else-if="section === 'review-downloads'">
        <el-table :data="reviewDownloads">
          <el-table-column prop="requirement_text" label="需求" show-overflow-tooltip />
          <el-table-column prop="git_url" label="来源">
            <template #default="{ row }">{{ row.git_url || 'zip' }}</template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" />
          <el-table-column label="操作" width="140">
            <template #default="{ row }">
              <el-button link type="primary" @click="saveExcel(row.id, `requirement-review-${row.id}.xlsx`)">下载</el-button>
              <el-button link type="danger" @click="removeTask(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="pagination-container">
          <el-pagination
            v-model:current-page="reviewDownloadPage.current"
            v-model:page-size="reviewDownloadPage.size"
            :page-sizes="[10, 20, 50]"
            layout="total, sizes, prev, pager, next"
            :total="reviewDownloadPage.total"
            @size-change="reloadReviewDownloadPage"
            @current-change="reloadReviewDownloadPage"
          />
        </div>
      </template>

      <template v-else-if="section === 'downloads'">
        <el-table :data="downloads">
          <el-table-column prop="git_url" label="来源">
            <template #default="{ row }">{{ row.git_url || 'zip' }}</template>
          </el-table-column>
          <el-table-column prop="created_at" label="创建时间" />
          <el-table-column label="操作" width="140">
            <template #default="{ row }">
              <el-button link type="primary" @click="saveExcel(row.id)">下载</el-button>
              <el-button link type="danger" @click="removeTask(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="pagination-container">
          <el-pagination
            v-model:current-page="downloadPage.current"
            v-model:page-size="downloadPage.size"
            :page-sizes="[10, 20, 50]"
            layout="total, sizes, prev, pager, next"
            :total="downloadPage.total"
            @size-change="reloadDownloadPage"
            @current-change="reloadDownloadPage"
          />
        </div>
      </template>
    </div>

    <el-dialog v-model="addressDialog" title="新增地址" width="480px">
      <el-form>
        <el-form-item label="名称"><el-input v-model="addressForm.name" /></el-form-item>
        <el-form-item label="Git 地址"><el-input v-model="addressForm.git_url" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addressDialog = false">取消</el-button>
        <el-button type="primary" @click="addAddress">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createAddress, createTask, deleteAddress, deleteTask, downloadTask,
  listActiveModels, listAddresses, listTasks
} from '@/api/code-monitor'

const route = useRoute()
const section = computed(() => {
  if (route.path.endsWith('/review-tasks')) return 'review-tasks'
  if (route.path.endsWith('/review-downloads')) return 'review-downloads'
  if (route.path.endsWith('/tasks')) return 'tasks'
  if (route.path.endsWith('/downloads')) return 'downloads'
  return 'addresses'
})
const pageTitle = computed(() => {
  if (section.value === 'tasks') return '扫描任务'
  if (section.value === 'downloads') return '下载结果'
  if (section.value === 'review-tasks') return '检查任务'
  if (section.value === 'review-downloads') return '下载报告'
  return '代码地址'
})
const addresses = ref([])
const tasks = ref([])
const downloads = ref([])
const models = ref([])
const taskPage = reactive({ current: 1, size: 20, total: 0 })
const downloadPage = reactive({ current: 1, size: 20, total: 0 })
const reviewPage = reactive({ current: 1, size: 20, total: 0 })
const reviewDownloadPage = reactive({ current: 1, size: 20, total: 0 })
const addressDialog = ref(false)
const addressForm = reactive({ name: '', git_url: '' })
const form = reactive({ addressId: null, file: null, token: '', modelConfigId: null })
const submitting = ref(false)
const reviewSubmitting = ref(false)
const reviewForm = reactive({ addressId: null, file: null, token: '', modelConfigId: null, requirement: '', requirementFile: null })
const requirementFileInput = ref(null)
const reviewTasks = ref([])
const reviewDownloads = ref([])
const statusText = { pending: '待执行', running: '执行中', succeeded: '成功', failed: '失败' }
let timer = null

function rowsOf(response) {
  const data = response.data
  if (Array.isArray(data)) return data
  return data.results || []
}

function firstString(value) {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = firstString(item)
      if (found) return found
    }
  }
  return ''
}

function actionErrorMessage(error, fallback) {
  const status = error.response?.status
  if (status === 401 || (status != null && status >= 500)) return null
  const data = error.response?.data
  if (Array.isArray(data)) return firstString(data) || fallback
  if (data && typeof data === 'object') {
    const nonField = firstString(data.non_field_errors)
    if (nonField) return nonField
    if (typeof data.detail === 'string' && data.detail) return data.detail
    const detailList = Array.isArray(data.detail) ? firstString(data.detail) : ''
    if (detailList) return detailList
    for (const [key, value] of Object.entries(data)) {
      if (key === 'non_field_errors' || key === 'detail') continue
      const found = firstString(value)
      if (found) return found
    }
  }
  if (typeof data === 'string' && data) return data
  if (error.code === 'ECONNABORTED') return '上传超时，请在扫描任务里刷新查看是否已提交'
  return fallback
}

async function loadAddresses() {
  addresses.value = rowsOf(await listAddresses({ page_size: 200 }))
}

function pagePayload(data, fallbackRows) {
  if (Array.isArray(data)) return { rows: fallbackRows, total: fallbackRows.length }
  return { rows: data.results || [], total: data.count || 0 }
}

async function loadTasks() {
  const response = await listTasks({
    page: taskPage.current,
    page_size: taskPage.size,
    task_type: 'api_extract',
  })
  const payload = pagePayload(response.data, rowsOf(response))
  tasks.value = payload.rows
  taskPage.total = payload.total
}

async function loadDownloads() {
  const response = await listTasks({
    page: downloadPage.current,
    page_size: downloadPage.size,
    has_result: 1,
    task_type: 'api_extract',
  })
  const payload = pagePayload(response.data, rowsOf(response))
  downloads.value = payload.rows
  downloadPage.total = payload.total
}

function reloadTaskPage() {
  loadTasks().catch(() => {})
}

function reloadDownloadPage() {
  loadDownloads().catch(() => {})
}

async function loadReviewTasks() {
  const response = await listTasks({
    page: reviewPage.current,
    page_size: reviewPage.size,
    task_type: 'requirement_review',
  })
  const payload = pagePayload(response.data, rowsOf(response))
  reviewTasks.value = payload.rows
  reviewPage.total = payload.total
}

async function loadReviewDownloads() {
  const response = await listTasks({
    page: reviewDownloadPage.current,
    page_size: reviewDownloadPage.size,
    has_result: 1,
    task_type: 'requirement_review',
  })
  const payload = pagePayload(response.data, rowsOf(response))
  reviewDownloads.value = payload.rows
  reviewDownloadPage.total = payload.total
}

function reloadReviewPage() {
  loadReviewTasks().catch(() => {})
}

function reloadReviewDownloadPage() {
  loadReviewDownloads().catch(() => {})
}

async function loadModels() {
  models.value = rowsOf(await listActiveModels()).filter(item => item.is_active)
}

async function addAddress() {
  try {
    await createAddress({ name: addressForm.name, git_url: addressForm.git_url })
    addressDialog.value = false
    addressForm.name = ''
    addressForm.git_url = ''
    await loadAddresses()
  } catch (error) {
    const msg = actionErrorMessage(error, '保存失败')
    if (msg) ElMessage.error(msg)
  }
}

async function removeAddress(id) {
  try {
    await deleteAddress(id)
    await loadAddresses()
  } catch (error) {
    const msg = actionErrorMessage(error, '删除失败')
    if (msg) ElMessage.error(msg)
  }
}

function onFile(event) {
  form.file = event.target.files[0] || null
  if (form.file) form.addressId = null
}

function onReviewFile(event) {
  reviewForm.file = event.target.files[0] || null
  if (reviewForm.file) reviewForm.addressId = null
}

function onRequirementFile(event) {
  reviewForm.requirementFile = event.target.files[0] || null
}

function clearRequirementFile() {
  reviewForm.requirementFile = null
  if (requirementFileInput.value) requirementFileInput.value.value = ''
}

function onReviewTokenPaste(event) {
  const text = event.clipboardData?.getData('text')?.trim() || ''
  if (!text) return
  event.preventDefault()
  reviewForm.token = text
}

function onTokenPaste(event) {
  const text = event.clipboardData?.getData('text')?.trim() || ''
  if (!text) return
  event.preventDefault()
  form.token = text
}

async function submitTask() {
  if (models.value.length === 0) {
    ElMessage.warning('没有已启用的模型配置')
    return
  }
  if (!form.modelConfigId) return
  if (!form.addressId && !form.file) {
    ElMessage.warning('请选择一个代码地址，或上传一个 zip')
    return
  }
  const token = form.token.trim()
  form.token = token
  if (form.addressId && !token) {
    ElMessage.warning('访问令牌是空的，请先粘贴。粘贴成功后会显示字数')
    return
  }
  const body = new FormData()
  body.append('model_config_id', form.modelConfigId)
  if (form.addressId) body.append('address_id', form.addressId)
  if (form.file) body.append('archive', form.file)
  if (token) body.append('token', token)
  submitting.value = true
  try {
    await createTask(body)
    form.token = ''
    taskPage.current = 1
    ElMessage.success('扫描已提交，可在下方列表查看进度。下载结果要等扫描成功')
  } catch (error) {
    const msg = actionErrorMessage(error, '提交失败')
    if (msg) ElMessage.error(msg)
  } finally {
    submitting.value = false
    taskPage.current = 1
    await loadTasks().catch(() => {})
  }
}

async function submitReview() {
  if (models.value.length === 0) {
    ElMessage.warning('没有已启用的模型配置')
    return
  }
  if (!reviewForm.modelConfigId) {
    ElMessage.warning('请先选择模型')
    return
  }
  if (reviewSubmitting.value) return
  const requirement = reviewForm.requirement.trim()
  reviewForm.requirement = requirement
  if (!requirement && !reviewForm.requirementFile) {
    ElMessage.warning('请填写需求，或上传需求文件')
    return
  }
  if (!reviewForm.addressId && !reviewForm.file) {
    ElMessage.warning('请选择一个代码地址，或上传一个 zip')
    return
  }
  const token = reviewForm.token.trim()
  reviewForm.token = token
  if (reviewForm.addressId && !token) {
    ElMessage.warning('访问令牌是空的，请先粘贴。粘贴成功后会显示字数')
    return
  }
  const body = new FormData()
  body.append('task_type', 'requirement_review')
  if (reviewForm.requirementFile) body.append('requirement_file', reviewForm.requirementFile)
  else body.append('requirement_text', requirement)
  body.append('model_config_id', reviewForm.modelConfigId)
  if (reviewForm.addressId) body.append('address_id', reviewForm.addressId)
  if (reviewForm.file) body.append('archive', reviewForm.file)
  if (token) body.append('token', token)
  reviewSubmitting.value = true
  try {
    await createTask(body)
    reviewForm.token = ''
    clearRequirementFile()
    reviewPage.current = 1
    ElMessage.success('检查已提交，可在下方列表查看进度')
  } catch (error) {
    const msg = actionErrorMessage(error, '提交失败')
    if (msg) ElMessage.error(msg)
  } finally {
    reviewSubmitting.value = false
    reviewPage.current = 1
    await loadReviewTasks().catch(() => {})
  }
}

async function removeTask(id) {
  try {
    await ElMessageBox.confirm('确定删除这条记录？', '删除', { type: 'warning' })
  } catch {
    return
  }
  const onReviewDownloads = section.value === 'review-downloads'
  const onDownloads = section.value === 'downloads' || onReviewDownloads
  const onReview = section.value === 'review-tasks' || onReviewDownloads
  const page = onReviewDownloads ? reviewDownloadPage : onDownloads ? downloadPage : onReview ? reviewPage : taskPage
  const rows = onReviewDownloads ? reviewDownloads.value : onDownloads ? downloads.value : onReview ? reviewTasks.value : tasks.value
  try {
    await deleteTask(id)
    if (rows.length === 1 && page.current > 1) page.current -= 1
    if (onReviewDownloads) await loadReviewDownloads()
    else if (onDownloads) await loadDownloads()
    else if (onReview) await loadReviewTasks()
    else await loadTasks()
  } catch (error) {
    const msg = actionErrorMessage(error, '删除失败')
    if (msg) ElMessage.error(msg)
  }
}

async function saveExcel(id, filename) {
  try {
    const response = await downloadTask(id)
    const url = URL.createObjectURL(response.data)
    const link = document.createElement('a')
    link.href = url
    link.download = filename || `api-extract-${id}.xlsx`
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    const msg = actionErrorMessage(error, '下载失败')
    if (msg) ElMessage.error(msg)
  }
}

async function loadSection() {
  if (section.value === 'downloads') await loadDownloads()
  else if (section.value === 'tasks') await loadTasks()
  else if (section.value === 'review-downloads') await loadReviewDownloads()
  else if (section.value === 'review-tasks') await loadReviewTasks()
}

watch(section, () => {
  loadSection().catch(() => {})
})

onMounted(async () => {
  await Promise.all([loadAddresses(), loadModels(), loadSection()])
  timer = setInterval(() => {
    const reviewing = section.value === 'review-tasks'
    const rows = reviewing ? reviewTasks.value : tasks.value
    if ((section.value === 'tasks' || reviewing) && rows.some(item => item.status === 'pending' || item.status === 'running')) {
      if (reviewing) loadReviewTasks()
      else loadTasks()
    }
  }, 5000)
})

onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.hint { margin-left: 12px; color: #909399; }
.requirement-hint { display: block; margin-left: 0; margin-top: 6px; }
.el-textarea { max-width: 640px; }
.pagination-container { display: flex; justify-content: flex-end; margin-top: 16px; }
</style>
