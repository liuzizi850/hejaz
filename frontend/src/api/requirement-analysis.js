/**
 * 需求分析模块相关 API
 */
import request from '@/utils/api'

// ==================== 生成行为配置 ====================

// 获取所有生成行为配置
export function getGenerationConfigs(params) {
  return request({
    url: '/requirement-analysis/generation-config/',
    method: 'get',
    params
  })
}

// 获取生成行为配置详情
export function getGenerationConfigDetail(id) {
  return request({
    url: `/requirement-analysis/generation-config/${id}/`,
    method: 'get'
  })
}

// 创建生成行为配置
export function createGenerationConfig(data) {
  return request({
    url: '/requirement-analysis/generation-config/',
    method: 'post',
    data
  })
}

// 更新生成行为配置
export function updateGenerationConfig(id, data) {
  return request({
    url: `/requirement-analysis/generation-config/${id}/`,
    method: 'put',
    data
  })
}

// 删除生成行为配置
export function deleteGenerationConfig(id) {
  return request({
    url: `/requirement-analysis/generation-config/${id}/`,
    method: 'delete'
  })
}

// 获取活跃的生成行为配置
export function getActiveGenerationConfig() {
  return request({
    url: '/requirement-analysis/generation-config/active/',
    method: 'get'
  })
}

// ==================== AI 模型配置 ====================

// 获取所有 AI 模型配置
export function getAIModelConfigs(params) {
  return request({
    url: '/requirement-analysis/ai-models/',
    method: 'get',
    params
  })
}

// 获取活跃的 AI 模型配置
export function getActiveAIModelConfig(modelType, role) {
  return request({
    url: '/requirement-analysis/ai-models/active/',
    method: 'get',
    params: { model_type: modelType, role }
  })
}

// 创建 AI 模型配置
export function createAIModelConfig(data) {
  return request({
    url: '/requirement-analysis/ai-models/',
    method: 'post',
    data
  })
}

// 更新 AI 模型配置
export function updateAIModelConfig(id, data) {
  return request({
    url: `/requirement-analysis/ai-models/${id}/`,
    method: 'put',
    data
  })
}

// 删除 AI 模型配置
export function deleteAIModelConfig(id) {
  return request({
    url: `/requirement-analysis/ai-models/${id}/`,
    method: 'delete'
  })
}

// ==================== 提示词配置 ====================

// 获取所有提示词配置
export function getPromptConfigs(params) {
  return request({
    url: '/requirement-analysis/prompts/',
    method: 'get',
    params
  })
}

// 获取活跃的提示词配置
export function getActivePromptConfig(promptType) {
  return request({
    url: '/requirement-analysis/prompts/active/',
    method: 'get',
    params: { prompt_type: promptType }
  })
}

// 创建提示词配置
export function createPromptConfig(data) {
  return request({
    url: '/requirement-analysis/prompts/',
    method: 'post',
    data
  })
}

// 更新提示词配置
export function updatePromptConfig(id, data) {
  return request({
    url: `/requirement-analysis/prompts/${id}/`,
    method: 'put',
    data
  })
}

// 删除提示词配置
export function deletePromptConfig(id) {
  return request({
    url: `/requirement-analysis/prompts/${id}/`,
    method: 'delete'
  })
}

// ==================== 需求质量审查 ====================

export function listQualityReviews(params) {
  return request({
    url: '/requirement-analysis/quality-reviews/',
    method: 'get',
    params
  })
}

export function createQualityReview(data) {
  const isForm = typeof FormData !== 'undefined' && data instanceof FormData
  return request({
    url: '/requirement-analysis/quality-reviews/',
    method: 'post',
    data,
    timeout: 150000,
    headers: isForm ? { 'Content-Type': 'multipart/form-data' } : undefined
  })
}

export function deleteQualityReview(id) {
  return request({
    url: `/requirement-analysis/quality-reviews/${id}/`,
    method: 'delete'
  })
}

// ==================== 需求文档撰写 ====================

export function listRequirementDrafts(params) {
  return request({
    url: '/requirement-analysis/drafts/',
    method: 'get',
    params
  })
}

export function getRequirementDraft(id) {
  return request({
    url: `/requirement-analysis/drafts/${id}/`,
    method: 'get'
  })
}

export function createRequirementDraft(data) {
  return request({
    url: '/requirement-analysis/drafts/',
    method: 'post',
    data,
    timeout: 150000
  })
}

export function updateRequirementDraft(id, data) {
  return request({
    url: `/requirement-analysis/drafts/${id}/`,
    method: 'patch',
    data
  })
}

export function deleteRequirementDraft(id) {
  return request({
    url: `/requirement-analysis/drafts/${id}/`,
    method: 'delete'
  })
}

export function finalizeRequirementDraft(id) {
  return request({
    url: `/requirement-analysis/drafts/${id}/finalize/`,
    method: 'post'
  })
}

export function reviewRequirementDraft(id) {
  return request({
    url: `/requirement-analysis/drafts/${id}/review/`,
    method: 'post',
    timeout: 150000
  })
}
