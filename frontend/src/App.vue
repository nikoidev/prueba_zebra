<template>
  <div class="app-layout">
    <!-- Sidebar -->
    <aside class="sidebar">
      <ExecuteForm />
      <ExecutionHistory />
    </aside>

    <!-- Main area -->
    <main class="main-area">
      <div v-if="!store.executing && !store.result && !store.error" class="empty-state">
        <div class="empty-icon">🦓</div>
        <h2>Sistema Multi-Agente Zebra</h2>
        <p>Introduce una solicitud en el panel izquierdo y ejecuta el pipeline para ver el análisis completo.</p>
      </div>

      <ProgressTracker v-else-if="store.executing || (store.progressSteps.length > 0 && !store.result)" />

      <ResultViewer v-else-if="store.result" :result="store.result" />

      <div v-if="store.error && !store.executing" class="error-state">
        <i class="pi pi-exclamation-circle" />
        <p>{{ store.error }}</p>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { usePipelineStore } from './stores/pipeline'
import ExecuteForm from './components/ExecuteForm.vue'
import ProgressTracker from './components/ProgressTracker.vue'
import ResultViewer from './components/ResultViewer.vue'
import ExecutionHistory from './components/ExecutionHistory.vue'

const store = usePipelineStore()

onMounted(async () => {
  await store.loadProviders()
  await store.loadHistory()
})
</script>
