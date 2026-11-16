<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h1 class="page-title">需求质量审查</h1>
        <p class="page-desc">审查完整性、一致性、可测性，标出歧义、缺失和冲突。高优先级问题会拦截，不进入用例设计。</p>
      </div>
    </div>

    <div class="card-container">
      <el-form label-width="100px">
        <el-form-item label="需求标题" required>
          <el-input v-model="form.title" maxlength="200" placeholder="例如：手机号验证码登录" />
        </el-form-item>
        <el-form-item label="关联项目">
          <el-select v-model="form.project" clearable placeholder="可选">
            <el-option v-for="item in projects" :key="item.id" :label="item.name" :value="item.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="需求正文" required>
          <el-input
            v-model="form.text"
            type="textarea"
            :rows="10"
            placeholder="粘贴需求。写清角色、前置、正常和异常、边界、状态变化、验收标准。"
          />
        </el-form-item>
        <el-form-item label="或上传文件">
          <input type="file" accept=".txt,.md,.docx,.pdf" @change="onFile" />
          <span class="hint">txt、md、docx、pdf。填了正文时以正文为准。</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="submitting" @click="submit">开始审查</el-button>
        </el-form-item>
      </el-form>
    </div>

    <div v-if="report" class="card-container report">
      <div class="report-head">
        <div>
          <h2>{{ report.title }}</h2>
          <p class="summary">{{ report.summary }}</p>
        </div>
        <el-tag v-if="report.verdict" :type="verdictType(report.verdict)" size="large">
          {{ report.verdict_display || verdictLabel[report.verdict] }}
        </el-tag>
        <el-tag v-else type="info" size="large">审查失败</el-tag>
      </div>
      <p v-if="report.error_message" class="error-text">{{ report.error_message }}</p>
      <p v-if="report.input_truncated" class="hint">正文超过 30000 字，本次只审查了前 30000 字。</p>
      <div v-if="report.status === 'completed'" class="scores">
        <div v-for="item in scoreItems" :key="item.key" class="score">
          <span>{{ item.label }}</span>
          <strong>{{ report[item.key] }}</strong>
        </div>
      </div>
      <div v-if="report.findings && report.findings.length" class="filters">
        <el-select v-model="dimensionFilter" clearable placeholder="维度">
          <el-option v-for="(label, key) in dimensionLabel" :key="key" :label="label" :value="key" />
        </el-select>
        <el-select v-model="issueFilter" clearable placeholder="问题类型">
          <el-option v-for="(label, key) in issueLabel" :key="key" :label="label" :value="key" />
        </el-select>
        <el-select v-model="severityFilter" clearable placeholder="严重程度">
          <el-option v-for="(label, key) in severityLabel" :key="key" :label="label" :value="key" />
        </el-select>
      </div>
      <el-table v-if="report.findings && report.findings.length" :data="visibleFindings">
        <el-table-column prop="id" label="编号" width="70" />
        <el-table-column label="维度" width="100">
          <template #default="{ row }">{{ dimensionLabel[row.dimension] || row.dimension }}</template>
        </el-table-column>
        <el-table-column label="类型" width="100">
          <template #default="{ row }">{{ issueLabel[row.issue_type] || row.issue_type }}</template>
        </el-table-column>
        <el-table-column label="程度" width="80">
          <template #default="{ row }">
            <el-tag :type="severityType(row.severity)" size="small">{{ severityLabel[row.severity] || row.severity }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="location" label="位置" width="140" />
        <el-table-column prop="quote" label="原文" min-width="160" />
        <el-table-column prop="problem" label="问题" min-width="220" />
        <el-table-column prop="suggestion" label="改法" min-width="220" />
      </el-table>
      <p v-else-if="report.status === 'completed'" class="hint">没有标出需求缺陷。</p>
    </div>

    <div class="card-container">
      <h2 class="section-title">审查记录</h2>
      <el-table :data="history" @row-click="openReport">
        <el-table-column prop="title" label="标题" min-width="180" />
        <el-table-column prop="project_name" label="项目" width="140" />
        <el-table-column label="结论" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.verdict" :type="verdictType(row.verdict)" size="small">{{ row.verdict_display }}</el-tag>
            <span v-else>失败</span>
          </template>
        </el-table-column>
        <el-table-column prop="overall_score" label="综合分" width="90" />
        <el-table-column prop="findings_count" label="问题数" width="90" />
        <el-table-column label="时间" min-width="180">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button link type="danger" @click.stop="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pagination-container">
        <el-pagination
          v-model:current-page="page"
          layout="total, prev, pager, next"
          :total="total"
          :page-size="20"
          @current-change="loadHistory"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/utils/api'
import { createQualityReview, deleteQualityReview, listQualityReviews } from '@/api/requirement-analysis'

const dimensionLabel = {
  completeness: '完整性',
  consistency: '一致性',
  testability: '可测性'
}
const issueLabel = {
  missing: '缺失',
  ambiguity: '歧义',
  conflict: '冲突',
  untestable: '不可测'
}
const severityLabel = { high: '高', medium: '中', low: '低' }
const verdictLabel = { pass: '可通过', revise: '需修改', block: '拦截' }

const form = reactive({ title: '', text: '', project: '', file: null })
const projects = ref([])
const submitting = ref(false)
const report = ref(null)
const history = ref([])
const page = ref(1)
const total = ref(0)
const dimensionFilter = ref('')
const issueFilter = ref('')
const severityFilter = ref('')

const scoreItems = [
  { key: 'completeness_score', label: '完整性' },
  { key: 'consistency_score', label: '一致性' },
  { key: 'testability_score', label: '可测性' },
  { key: 'overall_score', label: '综合' }
]

const visibleFindings = computed(() => {
  const rows = report.value?.findings || []
  return rows.filter(row => {
    if (dimensionFilter.value && row.dimension !== dimensionFilter.value) return false
    if (issueFilter.value && row.issue_type !== issueFilter.value) return false
    if (severityFilter.value && row.severity !== severityFilter.value) return false
    return true
  })
})

function verdictType(verdict) {
  if (verdict === 'pass') return 'success'
  if (verdict === 'revise') return 'warning'
  return 'danger'
}

function formatTime(value) {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(0, 19)
}

function severityType(severity) {
  if (severity === 'high') return 'danger'
  if (severity === 'medium') return 'warning'
  return 'info'
}

function onFile(event) {
  form.file = event.target.files?.[0] || null
}

function errorText(error, fallback) {
  return error?.response?.data?.error || fallback
}

async function submit() {
  if (!form.title.trim()) {
    ElMessage.error('请填写需求标题')
    return
  }
  if (!form.text.trim() && !form.file) {
    ElMessage.error('请粘贴需求正文，或上传文件')
    return
  }
  submitting.value = true
  try {
    let payload
    if (form.file && !form.text.trim()) {
      payload = new FormData()
      payload.append('title', form.title.trim())
      payload.append('file', form.file)
      if (form.project) payload.append('project', form.project)
    } else {
      payload = { title: form.title.trim(), text: form.text }
      if (form.project) payload.project = form.project
    }
    const response = await createQualityReview(payload)
    report.value = response.data
    dimensionFilter.value = ''
    issueFilter.value = ''
    severityFilter.value = ''
    if (response.data.status === 'failed') {
      ElMessage.error(response.data.error_message || '审查失败')
    } else if (response.data.verdict === 'block') {
      ElMessage.warning('存在高优先级需求缺陷，已拦截')
    } else {
      ElMessage.success('审查完成')
    }
    page.value = 1
    await loadHistory()
  } catch (error) {
    ElMessage.error(errorText(error, '审查失败'))
  } finally {
    submitting.value = false
  }
}

async function loadHistory() {
  const response = await listQualityReviews({ page: page.value })
  const data = response.data
  history.value = data.results || data
  total.value = data.count ?? history.value.length
}

function openReport(row) {
  report.value = row
  dimensionFilter.value = ''
  issueFilter.value = ''
  severityFilter.value = ''
}

async function remove(row) {
  try {
    await ElMessageBox.confirm('确定删除这条审查记录？', '删除', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteQualityReview(row.id)
    if (report.value?.id === row.id) report.value = null
    if (history.value.length === 1 && page.value > 1) page.value -= 1
    await loadHistory()
  } catch (error) {
    ElMessage.error(errorText(error, '删除失败'))
  }
}

onMounted(async () => {
  try {
    const response = await api.get('/projects/')
    projects.value = response.data.results || response.data
  } catch {
    projects.value = []
  }
  try {
    await loadHistory()
  } catch {
    history.value = []
  }
})
</script>

<style scoped>
.page-desc { margin: 6px 0 0; color: #606266; }
.report { margin-top: 16px; }
.report-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.report-head h2, .section-title { margin: 0 0 8px; font-size: 18px; }
.summary { margin: 0; white-space: pre-wrap; color: #303133; }
.scores { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 16px 0; }
.score { background: #f5f7fa; border-radius: 8px; padding: 12px 16px; }
.score span { display: block; color: #909399; }
.score strong { font-size: 28px; }
.filters { display: flex; gap: 12px; margin-bottom: 12px; }
.hint { margin-left: 12px; color: #909399; }
.error-text { color: #f56c6c; }
.pagination-container { display: flex; justify-content: flex-end; margin-top: 16px; }
.card-container + .card-container { margin-top: 16px; }
</style>
