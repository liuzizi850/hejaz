<template>
  <div class="share-page">
    <div v-if="error" class="share-error">{{ error }}</div>
    <iframe v-else class="share-frame" :src="reportSrc" title="report" />
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'

const route = useRoute()
const { t } = useI18n()
const token = computed(() => String(route.params.token || ''))
const error = computed(() => (token.value ? '' : t('appAutomation.aiRun.invalidShare')))
const reportSrc = computed(() => `/api/app-automation/ai-runs/share/${encodeURIComponent(token.value)}/`)
</script>

<style scoped>
.share-page {
  height: 100vh;
  margin: 0;
  background: #f5f7fa;
}
.share-frame {
  width: 100%;
  height: 100%;
  border: 0;
  background: #fff;
}
.share-error {
  padding: 40px;
  text-align: center;
  color: #f56c6c;
}
</style>
