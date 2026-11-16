<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h1 class="page-title">需求文档撰写</h1>
        <p class="page-desc">把口头说明、会议纪要或散乱笔记整理成结构化需求文档和可判定的验收标准。输入里没写清的内容放在待确认，不会补成已确定的规则。</p>
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
        <el-form-item label="原始输入" required>
          <el-input
            v-model="form.text"
            type="textarea"
            :rows="8"
            placeholder="粘贴口述、会议纪要或聊天记录。角色、流程、异常、边界写到什么程度，文档就整理到什么程度。"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="submitting" @click="submit">生成需求文档</el-button>
        </el-form-item>
      </el-form>
    </div>

    <div v-if="draft" class="card-container">
      <div class="report-head">
        <div>
          <h2>{{ draft.title }}</h2>
          <p v-if="draft.status === 'completed'" class="summary">
            验收标准 {{ draft.acceptance_count }} 条，待确认 {{ draft.open_questions_count }} 条
          </p>
        </div>
        <el-tag :type="draft.status === 'completed' ? 'success' : 'danger'" size="large">
          {{ draft.status_display || (draft.status === 'completed' ? '已完成' : '失败') }}
        </el-tag>
      </div>
      <p v-if="draft.error_message" class="error-text">{{ draft.error_message }}</p>
      <p v-if="draft.input_truncated" class="hint block-hint">原文超过 30000 字，本次只整理了前 30000 字。</p>

      <template v-if="draft.status === 'completed'">
        <el-alert
          v-if="draft.gaps_unlisted"
          class="gap-alert"
          type="warning"
          show-icon
          :closable="false"
          title="有章节标了「输入未说明」，待确认清单却是空的。请核对是不是把缺口写成了已确定内容。"
        />
        <div v-if="draft.open_questions && draft.open_questions.length" class="questions">
          <h3>待确认</h3>
          <div v-for="item in draft.open_questions" :key="item.id" class="question">
            <strong>{{ item.topic }}</strong>
            <p>{{ item.missing }}</p>
            <p v-if="item.impact" class="hint block-hint">{{ item.impact }}</p>
          </div>
        </div>

        <el-form label-width="100px">
          <el-form-item label="文档标题">
            <el-input v-model="editorTitle" maxlength="200" />
          </el-form-item>
          <el-form-item label="需求正文">
            <el-input v-model="editorText" type="textarea" :rows="18" />
          </el-form-item>
          <el-form-item>
            <el-button :loading="saving" @click="save">保存修改</el-button>
            <el-button :loading="finalizing" @click="finalize">保存为需求文档</el-button>
            <el-button type="primary" :loading="reviewing" @click="sendReview">送去质量审查</el-button>
            <span v-if="draft.document" class="hint">已关联需求文档 #{{ draft.document }}</span>
          </el-form-item>
        </el-form>

        <div v-if="reviewReport" class="review-banner">
          <div class="report-head">
            <p class="summary">{{ reviewReport.summary || reviewReport.error_message }}</p>
            <el-tag v-if="reviewReport.verdict" :type="verdictType(reviewReport.verdict)">
              {{ verdictLabel[reviewReport.verdict] || reviewReport.verdict }}
            </el-tag>
            <el-tag v-else type="info">审查失败</el-tag>
          </div>
          <p v-if="reviewReport.overall_score != null && reviewReport.status !== 'failed'" class="hint block-hint">
            综合分 {{ reviewReport.overall_score }}。完整问题列表在需求质量审查里。
          </p>
        </div>
      </template>
    </div>

    <div class="card-container">
      <h2 class="section-title">撰写记录</h2>
      <el-table :data="history" @row-click="openDraft">
        <el-table-column prop="title" label="标题" min-width="180" />
        <el-table-column prop="project_name" label="项目" width="140" />
        <el-table-column label="状态" width="90">
          <template #default="{ row }">{{ row.status_display }}</template>
        </el-table-column>
        <el-table-column prop="acceptance_count" label="验收标准" width="100" />
        <el-table-column prop="open_questions_count" label="待确认" width="90" />
        <el-table-column label="最近审查" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.latest_review_verdict" :type="verdictType(row.latest_review_verdict)" size="small">
              {{ verdictLabel[row.latest_review_verdict] }}
            </el-tag>
            <span v-else-if="row.latest_review_status === 'failed'">失败</span>
          </template>
        </el-table-column>
        <el-table-column label="时间" min-width="180">
          <template #default="{ row }">{{ formatTime(row.updated_at || row.created_at) }}</template>
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
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/utils/api'
import {
  createRequirementDraft,
  deleteRequirementDraft,
  finalizeRequirementDraft,
  getRequirementDraft,
  listRequirementDrafts,
  reviewRequirementDraft,
  updateRequirementDraft
} from '@/api/requirement-analysis'

const verdictLabel = { pass: '可通过', revise: '需修改', block: '拦截' }

const form = reactive({ title: '', text: '', project: '' })
const projects = ref([])
const submitting = ref(false)
const saving = ref(false)
const finalizing = ref(false)
const reviewing = ref(false)
const draft = ref(null)
const editorTitle = ref('')
const editorText = ref('')
const reviewReport = ref(null)
const history = ref([])
const page = ref(1)
const total = ref(0)

function verdictType(verdict) {
  if (verdict === 'pass') return 'success'
  if (verdict === 'revise') return 'warning'
  return 'danger'
}

function formatTime(value) {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(0, 19)
}

function errorText(error, fallback) {
  return error?.response?.data?.error || fallback
}

function applyDraft(data, review) {
  draft.value = data
  editorTitle.value = data.title || ''
  editorText.value = data.document_markdown || ''
  if (review) {
    reviewReport.value = review
    return
  }
  if (data.latest_review) {
    reviewReport.value = {
      id: data.latest_review,
      verdict: data.latest_review_verdict,
      status: data.latest_review_status,
      summary: data.latest_review_summary,
      overall_score: data.latest_review_overall_score,
      error_message: data.latest_review_status === 'failed' ? data.latest_review_summary : ''
    }
    return
  }
  reviewReport.value = null
}

async function submit() {
  if (!form.title.trim()) {
    ElMessage.error('请填写需求标题')
    return
  }
  if (form.text.trim().length < 20) {
    ElMessage.error('输入过短，至少需要 20 个字才能整理')
    return
  }
  submitting.value = true
  try {
    const payload = { title: form.title.trim(), text: form.text }
    if (form.project) payload.project = form.project
    const response = await createRequirementDraft(payload)
    applyDraft(response.data)
    if (response.data.status === 'failed') {
      ElMessage.error(response.data.error_message || '整理失败')
    } else {
      ElMessage.success('已生成需求文档')
    }
    page.value = 1
    await loadHistory()
  } catch (error) {
    ElMessage.error(errorText(error, '整理失败'))
  } finally {
    submitting.value = false
  }
}

async function save(options = {}) {
  if (!draft.value) return false
  saving.value = true
  try {
    const response = await updateRequirementDraft(draft.value.id, {
      title: editorTitle.value.trim(),
      document_markdown: editorText.value
    })
    applyDraft(response.data, reviewReport.value)
    if (!options.quiet) ElMessage.success('已保存')
    await loadHistory()
    return true
  } catch (error) {
    ElMessage.error(errorText(error, '保存失败'))
    return false
  } finally {
    saving.value = false
  }
}

function dirty() {
  if (!draft.value) return false
  return editorTitle.value.trim() !== draft.value.title || editorText.value !== (draft.value.document_markdown || '')
}

async function ensureSaved() {
  if (!dirty()) return true
  return save({ quiet: true })
}

async function finalize() {
  if (!draft.value) return
  finalizing.value = true
  try {
    if (!(await ensureSaved())) return
    const response = await finalizeRequirementDraft(draft.value.id)
    applyDraft(response.data, reviewReport.value)
    ElMessage.success('已保存为需求文档')
    await loadHistory()
  } catch (error) {
    ElMessage.error(errorText(error, '保存为需求文档失败'))
  } finally {
    finalizing.value = false
  }
}

async function sendReview() {
  if (!draft.value) return
  reviewing.value = true
  try {
    if (!(await ensureSaved())) return
    const response = await reviewRequirementDraft(draft.value.id)
    applyDraft(response.data.draft, response.data.review)
    const review = response.data.review
    if (review.status === 'failed') {
      ElMessage.error(review.error_message || '审查失败')
    } else if (review.verdict === 'block') {
      ElMessage.warning('存在高优先级需求缺陷，已拦截')
    } else {
      ElMessage.success('已送去质量审查')
    }
    await loadHistory()
  } catch (error) {
    ElMessage.error(errorText(error, '审查失败'))
  } finally {
    reviewing.value = false
  }
}

async function loadHistory() {
  const response = await listRequirementDrafts({ page: page.value })
  const data = response.data
  history.value = data.results || data
  total.value = data.count ?? history.value.length
}

async function openDraft(row) {
  try {
    const response = await getRequirementDraft(row.id)
    applyDraft(response.data)
  } catch (error) {
    ElMessage.error(errorText(error, '打开草稿失败'))
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm('确定删除这条撰写记录？', '删除', { type: 'warning' })
  } catch {
    return
  }
  try {
    await deleteRequirementDraft(row.id)
    if (draft.value?.id === row.id) {
      draft.value = null
      reviewReport.value = null
    }
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
.report-head { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
.report-head h2, .section-title { margin: 0 0 8px; font-size: 18px; }
.summary { margin: 0; white-space: pre-wrap; color: #303133; }
.questions { margin: 16px 0; }
.questions h3 { margin: 0 0 8px; font-size: 16px; }
.question { background: #f5f7fa; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px; }
.question p { margin: 4px 0 0; }
.gap-alert, .review-banner { margin: 16px 0; }
.hint { margin-left: 12px; color: #909399; }
.block-hint { margin-left: 0; }
.error-text { color: #f56c6c; }
.pagination-container { display: flex; justify-content: flex-end; margin-top: 16px; }
.card-container + .card-container { margin-top: 16px; }
</style>
