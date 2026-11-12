<template>
  <div class="assistant-layout">
    <!-- 左侧侧边栏 -->
    <div class="sidebar">
      <div class="new-chat-btn-wrapper">
        <el-button type="primary" class="new-chat-btn" @click="startNewChat" :icon="Plus">
          {{ $t('assistant.newChat') }}
        </el-button>
      </div>
      
      <div class="history-list">
        <div class="history-label">{{ $t('assistant.historyChat') }}</div>
        <div class="session-scroll-area">
          <div 
            v-for="session in historySessionsDescending" 
            :key="session.id ?? session.session_id"
            :class="['session-item', { active: isSessionActive(session) }]"
            @click="switchToSession(session)"
          >
            <div class="session-title-wrapper">
              <el-icon class="chat-icon"><ChatDotRound /></el-icon>
              <span class="session-title" :title="session.title">{{ session.title || $t('assistant.newChat') }}</span>
            </div>
            <div class="session-actions" @click.stop>
              <el-popconfirm :title="$t('assistant.deleteSessionConfirm')" @confirm="deleteSession(session.id)">
                <template #reference>
                  <el-icon class="delete-icon"><Delete /></el-icon>
                </template>
              </el-popconfirm>
            </div>
          </div>
        </div>
      </div>
      
      <div class="user-profile">
        <el-dropdown trigger="click" @command="handleCommand">
          <div class="user-info">
            <el-avatar :size="32" :icon="UserFilled" />
            <span class="username">{{ userStore.user?.username || $t('assistant.user') }}</span>
            <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="home">{{ $t('assistant.goHome') }}</el-dropdown-item>
              <el-dropdown-item command="logout" divided>{{ $t('assistant.logout') }}</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <!-- 右侧主内容区 -->
    <div class="main-content">
      <!-- 场景1：新会话（居中输入框） -->
      <div v-if="isNewChatMode" class="welcome-screen">
        <div class="welcome-content">
          <div class="logo-area">
            <div class="logo-circle">
              <el-icon><Cpu /></el-icon>
            </div>
            <h1>{{ $t('assistant.title') }}</h1>
            <p>{{ $t('assistant.subtitle') }}</p>
          </div>
          
          <div class="center-input-wrapper">
            <el-input
              v-model="inputMessage"
              type="textarea"
              :rows="3"
              :placeholder="$t('assistant.inputPlaceholder')"
              class="center-input"
              resize="none"
              @keydown.enter.exact.prevent="handleEnter"
            />
            <div class="input-actions">
              <el-button 
                type="primary" 
                circle 
                :icon="Promotion" 
                :disabled="!inputMessage.trim()"
                @click="sendMessage"
              />
            </div>
          </div>
          
          <div class="suggestion-chips">
            <div class="chip" @click="useSuggestion($t('assistant.suggestions.apiTestQuestion'))">{{ $t('assistant.suggestions.apiTest') }}</div>
            <div class="chip" @click="useSuggestion($t('assistant.suggestions.performancePlanQuestion'))">{{ $t('assistant.suggestions.performancePlan') }}</div>
            <div class="chip" @click="useSuggestion($t('assistant.suggestions.testTheoryQuestion'))">{{ $t('assistant.suggestions.testTheory') }}</div>
            <div class="chip" @click="useSuggestion($t('assistant.suggestions.automationDebugQuestion'))">{{ $t('assistant.suggestions.automationDebug') }}</div>
          </div>
        </div>
      </div>

      <!-- 场景2：对话界面 -->
      <div v-else class="chat-screen">
        <div class="chat-header">
          <span class="chat-title">{{ currentSession?.title || $t('assistant.newChat') }}</span>
          <span class="chat-time" v-if="currentSession">{{ formatDate(currentSession.updated_at) }}</span>
        </div>
        
        <div class="messages-container" ref="messagesContainer" @click="onMessagesClick">
          <div 
            v-for="(message, index) in messages" 
            :key="message.id || index"
            :class="['message-row', message.role]"
          >
            <div class="avatar">
              <el-avatar v-if="message.role === 'user'" :size="36" :icon="User" class="user-avatar" />
              <el-avatar v-else :size="36" :icon="Cpu" class="ai-avatar" />
            </div>
            <div class="message-bubble">
              <div class="message-content">
                <template v-for="(part, partIndex) in messageParts(message)" :key="partIndex">
                  <br v-if="part.type === 'break'">
                  <pre v-else-if="part.type === 'codeblock'"><code>{{ part.text }}</code></pre>
                  <code v-else-if="part.type === 'code'">{{ part.text }}</code>
                  <button
                    v-else-if="part.type === 'cite'"
                    type="button"
                    class="kb-cite"
                    :data-cite="part.index"
                    :title="part.title"
                  >{{ part.label }}</button>
                  <template v-else>{{ part.text }}</template>
                </template>
              </div>
              <div v-if="sourceCards(message).length" class="kb-sources">
                <div class="kb-sources-label">{{ $t('assistant.sources') }}</div>
                <div class="kb-sources-row">
                  <button
                    v-for="card in sourceCards(message)"
                    :key="card.index"
                    type="button"
                    class="kb-source-card"
                    @click="openReference(message, card.index)"
                  >
                    <span class="kb-source-preview">
                      <img
                        v-if="card.image_id && imageUrls[card.image_id]"
                        :src="imageUrls[card.image_id]"
                        :alt="fileLabel(card.document_name)"
                      />
                      <span v-else class="kb-source-excerpt">{{ excerpt(card.content) }}</span>
                      <span class="kb-source-badge">{{ card.index + 1 }}</span>
                    </span>
                    <span class="kb-source-name" :title="sourceCaption(card)">{{ fileLabel(card.document_name) || $t('assistant.sourceUntitled') }}</span>
                  </button>
                </div>
              </div>
              <div class="message-status" v-if="message.isPending">
                <el-icon class="is-loading"><Loading /></el-icon> {{ $t('assistant.thinking') }}
              </div>
            </div>
          </div>
          
          <!-- 底部占位，确保滚动到底部 -->
          <div style="height: 20px;"></div>
        </div>

        <div class="chat-footer">
          <div class="input-box">
            <el-input
              v-model="inputMessage"
              type="textarea"
              :rows="1"
              :autosize="{ minRows: 1, maxRows: 5 }"
              :placeholder="$t('assistant.chatInputPlaceholder')"
              resize="none"
              @keydown.enter.exact.prevent="handleEnter"
            />
            <el-button 
              type="primary" 
              class="send-btn"
              :disabled="!inputMessage.trim() || sending"
              @click="sendMessage"
            >
              <el-icon><Promotion /></el-icon>
            </el-button>
          </div>
          <div class="footer-tip">{{ $t('assistant.aiDisclaimer') }}</div>
        </div>
      </div>
    </div>

    <el-dialog
      v-model="referenceVisible"
      :title="activeReferenceTitle"
      width="760px"
      append-to-body
      class="kb-reference-dialog"
    >
      <div v-if="activeReference" class="kb-reference-body">
        <div class="kb-reference-meta">
          <span>{{ fileLabel(activeReference.document_name) || $t('assistant.sourceUntitled') }}</span>
          <span v-if="activeReference.page">{{ $t('assistant.sourcePage', { page: activeReference.page }) }}</span>
        </div>
        <img
          v-if="activeReference.image_id && imageUrls[activeReference.image_id]"
          class="kb-reference-image"
          :src="imageUrls[activeReference.image_id]"
          :alt="fileLabel(activeReference.document_name)"
        />
        <pre v-if="activeReference.content" class="kb-reference-text">{{ activeReference.content }}</pre>
        <div v-else class="kb-reference-empty">{{ $t('assistant.sourceEmpty') }}</div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useUserStore } from '@/stores/user'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, ChatDotRound, User, Cpu, Promotion, Loading, UserFilled, ArrowDown } from '@element-plus/icons-vue'
import api from '@/utils/api'

const router = useRouter()
const userStore = useUserStore()
const { t, locale } = useI18n()

// 状态
const historySessions = ref([])
const currentSession = ref(null)
const messages = ref([])
const inputMessage = ref('')
const sending = ref(false)
const messagesContainer = ref(null)
const imageUrls = ref({})
const imageFailed = ref({})
const loadingImages = new Set()
const referenceVisible = ref(false)
const activeReference = ref(null)

const activeReferenceTitle = computed(() => {
  const name = fileLabel(activeReference.value?.document_name)
  return name || t('assistant.sources')
})

const handleCommand = (command) => {
  if (command === 'logout') {
    handleLogout()
  } else if (command === 'home') {
    router.push('/home')
  }
}

const handleLogout = () => {
  ElMessageBox.confirm(t('assistant.logoutConfirm'), t('assistant.logoutTitle'), {
    confirmButtonText: t('assistant.confirm'),
    cancelButtonText: t('assistant.cancel'),
    type: 'warning'
  }).then(() => {
    userStore.logout()
    router.push('/login')
    ElMessage.success(t('assistant.loggedOut'))
  }).catch(() => {})
}

// 计算属性
const historySessionsDescending = computed(() => {
  return [...historySessions.value].sort((a, b) => 
    new Date(b.updated_at) - new Date(a.updated_at)
  )
})

const isNewChatMode = computed(() => {
  // 没有当前会话，或还没落到数据库的临时会话，显示欢迎页
  return !currentSession.value?.id && messages.value.length === 0
})

const isSessionActive = (session) => {
  const currentId = currentSession.value?.id
  return currentId != null && session.id != null && currentId === session.id
}

// 方法
const formatDate = (dateString) => {
  if (!dateString) return ''
  const date = new Date(dateString)
  const now = new Date()
  const localeCode = locale.value === 'zh-cn' ? 'zh-CN' : 'en-US'
  // 如果是今天，只显示时间
  if (date.toDateString() === now.toDateString()) {
    return date.toLocaleTimeString(localeCode, { hour: '2-digit', minute: '2-digit' })
  }
  return date.toLocaleDateString(localeCode, { month: '2-digit', day: '2-digit' })
}

const fileLabel = (name) => {
  if (!name) return ''
  const parts = String(name).split(/[/\\]/)
  return parts[parts.length - 1]
}

const excerpt = (text) => String(text || '').replace(/\s+/g, ' ').trim().slice(0, 72)

const sourceCaption = (card) => {
  const name = fileLabel(card.document_name) || t('assistant.sourceUntitled')
  return card.page ? `${name} · ${t('assistant.sourcePage', { page: card.page })}` : name
}

const messageChunks = (message) => (
  Array.isArray(message?.references) ? message.references : []
)

const findChunk = (chunks, index) => (
  chunks.find(item => Number(item.index) === Number(index)) || null
)

const sourceCards = (message) => {
  const chunks = messageChunks(message)
  if (!chunks.length) return []
  const cited = []
  const push = (index) => {
    const chunk = findChunk(chunks, index)
    if (!chunk || cited.some(item => item.index === chunk.index)) return
    cited.push(chunk)
  }
  const content = message.content || ''
  const marker = /##(\d+)\$\$|\[ID:(\d+)\]/g
  let match = marker.exec(content)
  while (match) {
    push(Number(match[1] ?? match[2]))
    match = marker.exec(content)
  }
  const plain = /\[(\d+)\]/g
  match = plain.exec(content)
  while (match) {
    const index = Number(match[1]) - 1
    if (index >= 0) push(index)
    match = plain.exec(content)
  }
  return cited.length ? cited : chunks.slice(0, 8)
}

const pushText = (parts, text) => {
  if (!text) return
  const lines = text.split('\n')
  lines.forEach((line, lineIndex) => {
    if (line) parts.push({ type: 'text', text: line })
    if (lineIndex < lines.length - 1) parts.push({ type: 'break' })
  })
}

const appendFormatted = (parts, text, cites) => {
  const pattern = /`([^`]+)`|\uE000(\d+)\uE001/g
  let cursor = 0
  let found = pattern.exec(text)
  while (found) {
    if (found.index > cursor) pushText(parts, text.slice(cursor, found.index))
    if (found[1] != null) parts.push({ type: 'code', text: found[1] })
    else parts.push(cites[Number(found[2])])
    cursor = found.index + found[0].length
    found = pattern.exec(text)
  }
  if (cursor < text.length) pushText(parts, text.slice(cursor))
}

const messageParts = (message) => {
  const content = message?.content
  if (!content) return []
  const chunks = messageChunks(message)
  const cites = []
  let source = content
  if (chunks.length) {
    source = source.replace(/##(\d+)\$\$|\[ID:(\d+)\]|\[(\d+)\]/g, (all, markerIndex, idIndex, label) => {
      const index = label == null ? Number(markerIndex ?? idIndex) : Number(label) - 1
      const chunk = findChunk(chunks, index)
      if (!chunk) return all
      const token = `\uE000${cites.length}\uE001`
      cites.push({
        type: 'cite',
        index,
        label: index + 1,
        title: fileLabel(chunk.document_name) || t('assistant.sources'),
      })
      return token
    })
  } else {
    source = source
      .replace(/##(\d+)\$\$/g, (_, index) => `[${Number(index) + 1}]`)
      .replace(/\[ID:(\d+)\]/g, (_, index) => `[${Number(index) + 1}]`)
  }

  const parts = []
  const fence = /```([\s\S]*?)```/g
  let last = 0
  let match = fence.exec(source)
  while (match) {
    if (match.index > last) appendFormatted(parts, source.slice(last, match.index), cites)
    const codeText = match[1]
    const citeToken = /\uE000(\d+)\uE001/g
    let codeCursor = 0
    let citeMatch = citeToken.exec(codeText)
    if (!citeMatch) {
      parts.push({ type: 'codeblock', text: codeText })
    } else {
      while (citeMatch) {
        if (citeMatch.index > codeCursor) {
          parts.push({ type: 'codeblock', text: codeText.slice(codeCursor, citeMatch.index) })
        }
        parts.push(cites[Number(citeMatch[1])])
        codeCursor = citeMatch.index + citeMatch[0].length
        citeMatch = citeToken.exec(codeText)
      }
      if (codeCursor < codeText.length) parts.push({ type: 'codeblock', text: codeText.slice(codeCursor) })
    }
    last = match.index + match[0].length
    match = fence.exec(source)
  }
  if (last < source.length || !parts.length) appendFormatted(parts, source.slice(last), cites)
  return parts
}

const loadSourceImage = async (imageId) => {
  if (!imageId || imageUrls.value[imageId] || imageFailed.value[imageId] || loadingImages.has(imageId)) return
  loadingImages.add(imageId)
  try {
    const response = await api.get('/assistant/chat/reference_image/', {
      params: { image_id: imageId },
      responseType: 'blob',
      timeout: 60000,
    })
    const mediaType = response.headers['content-type'] || ''
    if (!mediaType.startsWith('image/')) {
      imageFailed.value = { ...imageFailed.value, [imageId]: true }
      return
    }
    imageUrls.value = {
      ...imageUrls.value,
      [imageId]: URL.createObjectURL(response.data),
    }
  } catch {
    imageFailed.value = { ...imageFailed.value, [imageId]: true }
  } finally {
    loadingImages.delete(imageId)
  }
}

const loadMessageImages = (list) => {
  for (const message of list || []) {
    for (const card of sourceCards(message)) {
      if (card.image_id) loadSourceImage(card.image_id)
    }
  }
}

const openReference = (message, index) => {
  const chunk = findChunk(messageChunks(message), Number(index))
  if (!chunk) return
  activeReference.value = chunk
  referenceVisible.value = true
  if (chunk.image_id) loadSourceImage(chunk.image_id)
}

const onMessagesClick = (event) => {
  const button = event.target.closest?.('.kb-cite')
  if (!button || !messagesContainer.value) return
  const row = button.closest('.message-row')
  const rows = messagesContainer.value.querySelectorAll('.message-row')
  const message = messages.value[Array.from(rows).indexOf(row)]
  if (message) openReference(message, button.dataset.cite)
}

const scrollToBottom = () => {
  nextTick(() => {
    if (messagesContainer.value) {
      messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
    }
  })
}

// 开启新会话，并取消上一条会话的选中
const startNewChat = () => {
  currentSession.value = null
  messages.value = []
  inputMessage.value = ''
}

// 切换会话
const switchToSession = async (session) => {
  if (currentSession.value?.id === session.id) return
  
  try {
    currentSession.value = { ...session }
    const response = await api.get(`/assistant/sessions/${session.id}/messages/`)
    messages.value = response.data
    scrollToBottom()
  } catch (error) {
    console.error('Load messages failed:', error)
    ElMessage.error(t('assistant.messages.loadMessageFailed'))
  }
}

// 删除会话
const deleteSession = async (sessionId) => {
  try {
    await api.delete(`/assistant/sessions/${sessionId}/`)
    historySessions.value = historySessions.value.filter(s => s.id !== sessionId)
    
    if (currentSession.value?.id === sessionId) {
      startNewChat()
    }
    ElMessage.success(t('assistant.messages.sessionDeleted'))
  } catch (error) {
    console.error('Delete session failed:', error)
    ElMessage.error(t('assistant.messages.deleteSessionFailed'))
  }
}

// 使用建议
const useSuggestion = (text) => {
  inputMessage.value = text
  sendMessage()
}

// 处理回车发送
const handleEnter = (e) => {
  if (!e.shiftKey && !sending.value) {
    sendMessage()
  }
}

// 发送消息
const sendMessage = async () => {
  const text = inputMessage.value.trim()
  if (!text || sending.value) return
  
  inputMessage.value = ''
  sending.value = true
  
  // 1. 立即上屏用户消息
  const tempUserMsg = {
    role: 'user',
    content: text,
    created_at: new Date().toISOString()
  }
  messages.value.push(tempUserMsg)
  
  // 2. 添加一个临时的"思考中"消息
  const tempAiMsg = {
    role: 'assistant',
    content: '',
    isPending: true
  }
  messages.value.push(tempAiMsg)
  scrollToBottom()
  
  try {
    // 如果是新会话（没有ID），先创建会话
    let sessionId = currentSession.value?.id
    let isFirstMessage = false
    
    if (!sessionId) {
      isFirstMessage = true
      const newSessionId = `session_${Date.now()}_${Math.random().toString(36).substring(2, 15)}`
      // 智能生成标题（取前10个字）
      const title = text.length > 10 ? text.substring(0, 10) + '...' : text
      
      const sessionRes = await api.post('/assistant/sessions/', {
        session_id: newSessionId,
        title: title
      })
      
      currentSession.value = sessionRes.data
      sessionId = currentSession.value.session_id // 注意：后端返回的是对象，这里需要用 session_id 字段
      
      // 立即添加到历史列表
      historySessions.value.unshift(currentSession.value)
    } else {
      // 如果是已有会话，使用 session_id 字段
      sessionId = currentSession.value.session_id
    }
    
    // 3. 发送请求
    const response = await api.post('/assistant/chat/send_message/', {
      session_id: sessionId,
      message: text
    }, {
      timeout: 60000
    })
    
    // 4. 替换临时消息为真实消息
    messages.value.pop() // 移除思考中
    messages.value.pop() // 移除临时用户消息（因为后端返回了完整的用户消息对象）
    
    messages.value.push(response.data.user_message)
    messages.value.push(response.data.assistant_message)
    
    // 更新会话的 conversation_id
    if (response.data.conversation_id && currentSession.value) {
      currentSession.value.conversation_id = response.data.conversation_id
    }
    
    // 如果是第一次对话，更新历史列表中的会话信息（比如 updated_at）
    if (!isFirstMessage) {
      const index = historySessions.value.findIndex(s => s.id === currentSession.value.id)
      if (index !== -1) {
        historySessions.value[index] = { ...currentSession.value, updated_at: new Date().toISOString() }
        // 重新排序（移到最前）
        const updatedSession = historySessions.value.splice(index, 1)[0]
        historySessions.value.unshift(updatedSession)
      }
    }
    
  } catch (error) {
    console.error('Send failed:', error)
    // 移除临时消息，显示错误
    messages.value.pop() // 移除思考中
    ElMessage.error(error.response?.data?.error || t('assistant.messages.sendFailed'))
  } finally {
    sending.value = false
    scrollToBottom()
  }
}

// 加载历史
const loadHistory = async () => {
  try {
    const response = await api.get('/assistant/sessions/')
    historySessions.value = response.data.results || response.data || []
  } catch (error) {
    console.error('Load history failed:', error)
  }
}

watch(messages, (list) => {
  loadMessageImages(list)
}, { deep: true })

onMounted(() => {
  loadHistory()
  startNewChat()
})

onBeforeUnmount(() => {
  Object.values(imageUrls.value).forEach((url) => URL.revokeObjectURL(url))
})
</script>

<style scoped lang="scss">
.assistant-layout {
  display: flex;
  height: 100vh;
  background: #fff;
  overflow: hidden;
}

/* 左侧侧边栏 */
.sidebar {
  width: 260px;
  background: #001529; /* 与主布局一致的深色背景 */
  border-right: 1px solid #1f1f1f;
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  color: rgba(255, 255, 255, 0.65);
  
  .new-chat-btn-wrapper {
    padding: 20px;
    
    .new-chat-btn {
      width: 100%;
      height: 40px;
      border-radius: 4px; /* 稍微减小圆角以匹配整体风格 */
      font-size: 14px;
      background: #1890ff;
      border-color: #1890ff;
      color: white;
      
      &:hover {
        background: #40a9ff;
        border-color: #40a9ff;
      }
    }
  }
  
  .history-list {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    
    .history-label {
      padding: 0 20px 10px;
      font-size: 12px;
      color: rgba(255, 255, 255, 0.45);
    }
    
    .session-scroll-area {
      flex: 1;
      overflow-y: auto;
      padding: 0 10px;
      
      &::-webkit-scrollbar {
        width: 4px;
      }
      &::-webkit-scrollbar-thumb {
        background: rgba(255, 255, 255, 0.2);
        border-radius: 2px;
      }
    }
    
    .session-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 10px 12px;
      margin-bottom: 4px;
      border-radius: 4px;
      cursor: pointer;
      transition: all 0.2s;
      color: rgba(255, 255, 255, 0.65);
      
      &:hover {
        background: rgba(255, 255, 255, 0.08);
        color: white;
      }
      
      &.active {
        background: #1890ff;
        color: white;
      }
      
      .session-title-wrapper {
        display: flex;
        align-items: center;
        gap: 8px;
        flex: 1;
        overflow: hidden;
        
        .chat-icon {
          font-size: 16px;
        }
        
        .session-title {
          font-size: 14px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
      }
      
      .session-actions {
        flex-shrink: 0;
        display: flex;
        align-items: center;
        
        .delete-icon {
          font-size: 16px;
          color: rgba(255, 255, 255, 0.55);
          &:hover {
            color: #ff7875;
          }
        }
      }

      &.active .session-actions .delete-icon {
        color: rgba(255, 255, 255, 0.92);
      }
    }
  }
  
  .user-profile {
    padding: 16px;
    border-top: 1px solid #1f1f1f;
    
    .user-info {
      display: flex;
      align-items: center;
      cursor: pointer;
      padding: 8px;
      border-radius: 4px;
      transition: all 0.2s;
      
      &:hover {
        background: rgba(255, 255, 255, 0.08);
      }
      
      .username {
        margin: 0 8px;
        font-size: 14px;
        color: rgba(255, 255, 255, 0.85);
        flex: 1;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      
      .el-icon {
        color: rgba(255, 255, 255, 0.45);
      }
    }
  }
}

/* 右侧主内容区 */
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  position: relative;
  background: #fff;
}

/* 场景1：欢迎页（新会话） */
.welcome-screen {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding-bottom: 100px;
  
  .welcome-content {
    width: 100%;
    max-width: 800px;
    padding: 0 20px;
    display: flex;
    flex-direction: column;
    align-items: center;
  }
  
  .logo-area {
    text-align: center;
    margin-bottom: 40px;
    
    .logo-circle {
      width: 80px;
      height: 80px;
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      margin: 0 auto 20px;
      box-shadow: 0 10px 20px rgba(102, 126, 234, 0.3);
      
      .el-icon {
        font-size: 40px;
        color: white;
      }
    }
    
    h1 {
      font-size: 28px;
      color: #303133;
      margin: 0 0 10px;
    }
    
    p {
      color: #909399;
      font-size: 16px;
      margin: 0;
    }
  }
  
  .center-input-wrapper {
    width: 100%;
    position: relative;
    margin-bottom: 30px;
    
    .center-input {
      :deep(.el-textarea__inner) {
        border-radius: 16px;
        padding: 16px 50px 16px 20px;
        font-size: 16px;
        box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
        border: 1px solid #e4e7ed;
        transition: all 0.3s;
        
        &:focus {
          box-shadow: 0 4px 20px rgba(64, 158, 255, 0.15);
          border-color: #409eff;
        }
      }
    }
    
    .input-actions {
      position: absolute;
      right: 10px;
      bottom: 10px;
    }
  }
  
  .suggestion-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    justify-content: center;
    
    .chip {
      padding: 8px 16px;
      background: #f5f7fa;
      border-radius: 20px;
      font-size: 14px;
      color: #606266;
      cursor: pointer;
      transition: all 0.2s;
      
      &:hover {
        background: #e6f1fc;
        color: #409eff;
      }
    }
  }
}

/* 场景2：对话页 */
.chat-screen {
  flex: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  
  .chat-header {
    height: 60px;
    border-bottom: 1px solid #f0f2f5;
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0 24px;
    flex-shrink: 0;
    
    .chat-title {
      font-size: 16px;
      font-weight: 600;
      color: #303133;
    }
    
    .chat-time {
      font-size: 12px;
      color: #909399;
    }
  }
  
  .messages-container {
    flex: 1;
    overflow-y: auto;
    padding: 24px;
    background: #fff;
    
    .message-row {
      display: flex;
      gap: 16px;
      margin-bottom: 24px;
      
      &.user {
        flex-direction: row-reverse;
        
        .message-bubble {
          background: #409eff;
          color: white;
          border-radius: 12px 12px 0 12px;
          
          :deep(pre) {
            background: rgba(0, 0, 0, 0.1);
          }
          
          :deep(code) {
            background: rgba(0, 0, 0, 0.1);
            color: #fff;
          }
        }
      }
      
      &.assistant {
        .message-bubble {
          max-width: min(880px, 88%);
          background: #f5f7fa;
          color: #303133;
          border-radius: 12px 12px 12px 0;
        }
      }
      
      .avatar {
        flex-shrink: 0;
        margin-top: 2px;
        
        .user-avatar {
          background: #c0c4cc;
        }
        
        .ai-avatar {
          background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
      }
      
      .message-bubble {
        max-width: 70%;
        padding: 12px 16px;
        font-size: 15px;
        line-height: 1.6;
        position: relative;
        
        .message-content {
          word-wrap: break-word;
          
          :deep(p) {
            margin: 0 0 8px 0;
            &:last-child { margin: 0; }
          }
          
          :deep(pre) {
            background: #282c34;
            color: #abb2bf;
            padding: 12px;
            border-radius: 8px;
            overflow-x: auto;
            margin: 8px 0;
          }
          
          :deep(code) {
            font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
            font-size: 13px;
          }

          :deep(.kb-cite) {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            min-width: 16px;
            height: 18px;
            margin: 0 2px;
            padding: 0 4px;
            border: none;
            border-radius: 4px;
            background: #e8f3ff;
            color: #1677ff;
            font-size: 12px;
            line-height: 18px;
            cursor: pointer;
            vertical-align: baseline;

            &::before { content: '['; }
            &::after { content: ']'; }

            &:hover {
              background: #1677ff;
              color: #fff;
            }
          }
        }

        .kb-sources {
          margin-top: 12px;
          padding-top: 10px;
          border-top: 1px solid #e4e7ed;
        }

        .kb-sources-label {
          margin-bottom: 8px;
          font-size: 12px;
          color: #909399;
        }

        .kb-sources-row {
          display: flex;
          gap: 10px;
          overflow-x: auto;
          padding-bottom: 4px;
        }

        .kb-source-card {
          flex: 0 0 128px;
          width: 128px;
          padding: 0;
          border: none;
          background: transparent;
          text-align: left;
          cursor: pointer;
        }

        .kb-source-preview {
          position: relative;
          display: block;
          height: 92px;
          overflow: hidden;
          border: 1px solid #e5e6eb;
          border-radius: 6px;
          background: #fff;

          img {
            width: 100%;
            height: 100%;
            object-fit: cover;
            object-position: top;
          }
        }

        .kb-source-excerpt {
          display: block;
          height: 100%;
          padding: 8px;
          overflow: hidden;
          color: #606266;
          font-size: 11px;
          line-height: 1.45;
        }

        .kb-source-badge {
          position: absolute;
          left: 6px;
          bottom: 6px;
          min-width: 18px;
          height: 18px;
          padding: 0 5px;
          border-radius: 9px;
          background: #f5222d;
          color: #fff;
          font-size: 12px;
          line-height: 18px;
          text-align: center;
        }

        .kb-source-name {
          display: block;
          margin-top: 4px;
          overflow: hidden;
          color: #909399;
          font-size: 11px;
          line-height: 1.3;
          white-space: nowrap;
          text-overflow: ellipsis;
        }

        .kb-source-card:hover .kb-source-preview {
          border-color: #1677ff;
        }
        
        .message-status {
          display: flex;
          align-items: center;
          gap: 6px;
          font-size: 13px;
          color: #909399;
          
          .is-loading {
            animation: rotating 2s linear infinite;
          }
        }
      }
    }
  }
  
  .chat-footer {
    padding: 20px 24px;
    border-top: 1px solid #f0f2f5;
    background: #fff;
    
    .input-box {
      position: relative;
      border: 1px solid #e4e7ed;
      border-radius: 12px;
      padding: 8px;
      background: #fff;
      transition: all 0.3s;
      
      &:focus-within {
        border-color: #409eff;
        box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.1);
      }
      
      :deep(.el-textarea__inner) {
        border: none;
        box-shadow: none;
        padding: 8px 50px 8px 8px;
        background: transparent;
      }
      
      .send-btn {
        position: absolute;
        right: 8px;
        bottom: 8px;
        width: 32px;
        height: 32px;
        padding: 0;
        border-radius: 8px;
      }
    }
    
    .footer-tip {
      text-align: center;
      font-size: 12px;
      color: #c0c4cc;
      margin-top: 8px;
    }
  }
}

.kb-reference-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.kb-reference-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: #606266;
  font-size: 13px;
}

.kb-reference-image {
  display: block;
  max-width: 100%;
  max-height: 420px;
  object-fit: contain;
  object-position: top;
  border: 1px solid #e5e6eb;
  border-radius: 8px;
  background: #fff;
}

.kb-reference-text {
  margin: 0;
  max-height: 240px;
  overflow: auto;
  padding: 12px;
  border-radius: 8px;
  background: #f5f7fa;
  color: #303133;
  font-family: inherit;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.kb-reference-empty {
  color: #909399;
  font-size: 13px;
}

@keyframes rotating {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}
</style>