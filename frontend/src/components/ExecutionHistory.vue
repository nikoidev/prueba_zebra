<template>
  <div class="history-panel">
    <div class="history-header">
      <span class="history-title">Historial</span>
      <Button icon="pi pi-refresh" text size="small" @click="store.loadHistory()" :loading="store.historyLoading" />
    </div>

    <div v-if="store.history.length === 0 && !store.historyLoading" class="history-empty">
      Sin ejecuciones previas
    </div>

    <div
      v-for="ex in store.history"
      :key="ex.id"
      class="history-item"
      @click="store.viewExecution(ex.id)"
    >
      <div class="history-item-top">
        <Tag
          :value="ex.final_state"
          :severity="ex.final_state === 'DONE' ? 'success' : 'danger'"
          class="state-tag"
        />
        <span class="history-conf" v-if="ex.overall_confidence">
          {{ (ex.overall_confidence * 100).toFixed(0) }}%
        </span>
        <span class="history-tokens">{{ (ex.total_tokens ?? 0).toLocaleString() }}t</span>
      </div>
      <div class="history-request">{{ truncate(ex.original_request, 60) }}</div>
      <div class="history-date">{{ formatDate(ex.created_at) }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import Button from 'primevue/button'
import Tag from 'primevue/tag'
import { usePipelineStore } from '../stores/pipeline'

const store = usePipelineStore()

function truncate(s: string, n: number) {
  return s.length > n ? s.slice(0, n) + '…' : s
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString('es', { dateStyle: 'short', timeStyle: 'short' })
}
</script>
