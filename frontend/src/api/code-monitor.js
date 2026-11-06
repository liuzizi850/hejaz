import request from '@/utils/api'

export function listAddresses(params) {
  return request({ url: '/code-monitor/addresses/', method: 'get', params })
}

export function createAddress(data) {
  return request({ url: '/code-monitor/addresses/', method: 'post', data })
}

export function deleteAddress(id) {
  return request({ url: `/code-monitor/addresses/${id}/`, method: 'delete' })
}

export function listTasks(params) {
  return request({ url: '/code-monitor/tasks/', method: 'get', params })
}

export function createTask(formData) {
  return request({
    url: '/code-monitor/tasks/',
    method: 'post',
    data: formData,
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

export function downloadTask(id) {
  return request({
    url: `/code-monitor/tasks/${id}/download/`,
    method: 'get',
    responseType: 'blob'
  })
}

export function listActiveModels() {
  return request({
    url: '/requirement-analysis/ai-models/',
    method: 'get',
    params: { is_active: true, page_size: 200 }
  })
}
