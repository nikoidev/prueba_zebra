<template>
  <div class="app-layout">
    <!-- Sidebar -->
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">D</div>
        <div class="brand-text">
          <div class="brand-title">Disashop <span>AI Lab</span></div>
          <div class="brand-sub">Service Launch Co-Pilot</div>
        </div>
      </div>
      <ExecuteForm />
      <ExecutionHistory />
    </aside>

    <!-- Main area -->
    <main class="main-area">
      <div v-if="!store.executing && !store.result && !store.error" class="empty-state">
        <div class="empty-icon">🚀</div>
        <h2>Service Launch Co-Pilot</h2>
        <p>
          Co-piloto multi-agente para acelerar el lanzamiento de nuevos servicios en la red Disashop.
          Selecciona un escenario o describe una iniciativa de lanzamiento en el panel izquierdo.
        </p>
        <p class="empty-pipeline">
          Decomposer · Análisis multi-área · Director de Programa · Comité de Validación · Riesgos & Compliance
        </p>
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
