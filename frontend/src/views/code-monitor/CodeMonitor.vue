<template>
  <div class="code-monitor">
    <h2>代码监控</h2>
    <div class="layout">
      <el-menu :default-active="section" class="menu" @select="section = $event">
        <el-sub-menu index="extract">
          <template #title>提取 API</template>
          <el-menu-item index="addresses">代码地址</el-menu-item>
          <el-menu-item index="tasks">扫描任务</el-menu-item>
          <el-menu-item index="downloads">下载结果</el-menu-item>
        </el-sub-menu>
      </el-menu>

      <div class="panel">
        <template v-if="section === 'addresses'">
          <el-button type="primary" @click="addressDialog = true">新增地址</el-button>
          <el-table :data="addresses" style="margin-top: 12px">
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
              <el-input v-model="form.token" type="password" show-password placeholder="私有仓库填写，不会保存" />
            </el-form-item>
            <el-form-item label="模型">
              <el-select v-model="form.modelConfigId" placeholder="选择已启用模型">
                <el-option v-for="item in models" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :disabled="!models.length" @click="submitTask">开始扫描</el-button>
              <span v-if="!models.length" class="hint">没有已启用的模型配置</span>
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
          </el-table>
        </template>

        <template v-else>
          <el-table :data="downloads">
            <el-table-column prop="git_url" label="来源">
              <template #default="{ row }">{{ row.git_url || 'zip' }}</template>
            </el-table-column>
            <el-table-column prop="created_at" label="创建时间" />
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button link type="primary" @click="saveExcel(row.id)">下载</el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>
      </div>
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
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  createAddress, createTask, deleteAddress, downloadTask,
  listActiveModels, listAddresses, listTasks
} from '@/api/code-monitor'

const section = ref('addresses')
const addresses = ref([])
const tasks = ref([])
const models = ref([])
const addressDialog = ref(false)
const addressForm = reactive({ name: '', git_url: '' })
const form = reactive({ addressId: null, file: null, token: '', modelConfigId: null })
const statusText = { pending: '待执行', running: '执行中', succeeded: '成功', failed: '失败' }
let timer = null

const downloads = computed(() => tasks.value.filter(item => item.status === 'succeeded' && item.has_result))

function rowsOf(response) {
  const data = response.data
  if (Array.isArray(data)) return data
  return data.results || []
}

function actionErrorMessage(error, fallback) {
  const status = error.response?.status
  if (status === 401 || (status != null && status >= 500)) return null
  const data = error.response?.data
  if (data?.non_field_errors?.[0]) return data.non_field_errors[0]
  if (typeof data?.detail === 'string') return data.detail
  return fallback
}

async function loadAddresses() {
  addresses.value = rowsOf(await listAddresses({ page_size: 200 }))
}

async function loadTasks() {
  tasks.value = rowsOf(await listTasks({ page_size: 200 }))
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

async function submitTask() {
  if (!form.modelConfigId) {
    ElMessage.warning('没有已启用的模型配置')
    return
  }
  if (!form.addressId && !form.file) {
    ElMessage.warning('请选择一个代码地址，或上传一个 zip')
    return
  }
  const body = new FormData()
  body.append('model_config_id', form.modelConfigId)
  if (form.addressId) body.append('address_id', form.addressId)
  if (form.file) body.append('archive', form.file)
  if (form.token) body.append('token', form.token)
  try {
    await createTask(body)
    form.token = ''
    await loadTasks()
    ElMessage.success('扫描已提交')
  } catch (error) {
    const msg = actionErrorMessage(error, '提交失败')
    if (msg) ElMessage.error(msg)
  }
}

async function saveExcel(id) {
  try {
    const response = await downloadTask(id)
    const url = URL.createObjectURL(response.data)
    const link = document.createElement('a')
    link.href = url
    link.download = `api-extract-${id}.xlsx`
    link.click()
    URL.revokeObjectURL(url)
  } catch (error) {
    const msg = actionErrorMessage(error, '下载失败')
    if (msg) ElMessage.error(msg)
  }
}

onMounted(async () => {
  await Promise.all([loadAddresses(), loadTasks(), loadModels()])
  timer = setInterval(() => {
    if (tasks.value.some(item => item.status === 'pending' || item.status === 'running')) {
      loadTasks()
    }
  }, 5000)
})

onUnmounted(() => clearInterval(timer))
</script>

<style scoped>
.code-monitor { padding: 16px; }
.layout { display: flex; gap: 16px; margin-top: 12px; }
.menu { width: 220px; }
.panel { flex: 1; }
.hint { margin-left: 12px; color: #909399; }
</style>
