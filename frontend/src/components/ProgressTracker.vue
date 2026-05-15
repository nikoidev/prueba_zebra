<template>
  <div class="progress-tracker">
    <h3 class="tracker-title">
      <i class="pi pi-spin pi-spinner" v-if="store.executing" />
      <i class="pi pi-check-circle" v-else style="color: var(--p-green-400)" />
      Pipeline en progreso
    </h3>

    <div class="steps">
      <div
        v-for="(step, i) in allSteps"
        :key="i"
        class="step"
        :class="{
          'step--done': isCompleted(step.state),
          'step--active': isActive(step.state),
          'step--pending': isPending(step.state),
        }"
      >
        <div class="step-icon">
          <i v-if="isCompleted(step.state)" class="pi pi-check" />
          <i v-else-if="isActive(step.state)" class="pi pi-spin pi-spinner" />
          <i v-else class="pi pi-circle" />
        </div>
        <div class="step-body">
          <div class="step-name">{{ step.label }}</div>
          <div v-if="getTrace(step.state)" class="step-meta">
            <span class="meta-item">
              <i class="pi pi-clock" />
              {{ getTrace(step.state)!.duration_ms?.toFixed(0) }}ms
            </span>
            <span class="meta-item">
              <i class="pi pi-database" />
              {{ getTrace(step.state)!.tokens?.toLocaleString() }} tokens
            </span>
            <span v-if="getTrace(step.state)!.from_cache" class="meta-item cache-badge">
              <i class="pi pi-bolt" /> cache
            </span>
            <span class="meta-item model-badge">{{ getTrace(step.state)!.model_used }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { usePipelineStore } from '../stores/pipeline'

const store = usePipelineStore()

const PIPELINE_STATES = [
  { state: 'DECOMPOSING', label: 'Decomposer — Descomponer solicitud' },
  { state: 'ANALYZING', label: 'Domain Expert — Analizar dominios' },
  { state: 'ARCHITECTING', label: 'Architect — Diseñar solución' },
  { state: 'REVIEWING', label: 'Reviewer — Revisar calidad' },
  { state: 'FINALIZING', label: 'Risk Analyst — Analizar riesgos' },
  { state: 'DONE', label: 'Completado' },
]

const allSteps = computed(() => PIPELINE_STATES)

// La ultima traza completada para un estado dado
function getTrace(state: string) {
  return store.progressSteps.find(s => {
    // El progreso se emite con el NEXT state, mapear inverso
    const prev = prevState(state)
    return prev ? s.state === state : false
  }) ?? store.progressSteps.find(s => nextState(s.state) === state)
}

function nextState(state: string) {
  const map: Record<string, string> = {
    DECOMPOSING: 'ANALYZING',
    ANALYZING: 'ARCHITECTING',
    ARCHITECTING: 'REVIEWING',
    REVIEWING: 'FINALIZING',
    FINALIZING: 'DONE',
  }
  return map[state]
}

function prevState(state: string) {
  const map: Record<string, string> = {
    ANALYZING: 'DECOMPOSING',
    ARCHITECTING: 'ANALYZING',
    REVIEWING: 'ARCHITECTING',
    FINALIZING: 'REVIEWING',
    DONE: 'FINALIZING',
  }
  return map[state]
}

const completedStates = computed(() => new Set(store.progressSteps.map(s => s.state)))

const currentState = computed(() =>
  store.progressSteps.length > 0
    ? store.progressSteps[store.progressSteps.length - 1].state
    : 'DECOMPOSING'
)

function isCompleted(state: string) {
  if (!store.executing && store.result) return true
  return completedStates.value.has(state)
}

function isActive(state: string) {
  if (!store.executing) return false
  const order = PIPELINE_STATES.map(s => s.state)
  const currentIdx = order.indexOf(currentState.value)
  const stateIdx = order.indexOf(state)
  return stateIdx === currentIdx + 1
}

function isPending(state: string) {
  return !isCompleted(state) && !isActive(state)
}
</script>
