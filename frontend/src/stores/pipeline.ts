import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  fetchProviders,
  fetchModels,
  fetchExecutions,
  fetchExecutionDetail,
  executeViaWebSocket,
  type ProgressMessage,
} from '../api'

export interface ProgressStep {
  state: string
  agent_name: string | null
  duration_ms?: number
  tokens?: number
  from_cache?: boolean
  model_used?: string
  revision_count: number
}

export const usePipelineStore = defineStore('pipeline', () => {
  // Provider / model
  const providers = ref<string[]>([])
  const selectedProvider = ref('')
  const selectedModel = ref('')
  const modelsByProvider = ref<Record<string, string[]>>({})

  // Execution state
  const executing = ref(false)
  const progressSteps = ref<ProgressStep[]>([])
  const result = ref<any>(null)
  const error = ref<string | null>(null)

  // History
  const history = ref<any[]>([])
  const historyLoading = ref(false)

  async function loadProviders() {
    try {
      const data = await fetchProviders()
      providers.value = data.providers
      selectedProvider.value = data.default_provider
      selectedModel.value = data.default_model
      // Pre-cargar modelos del provider default
      await loadModels(data.default_provider)
    } catch (e: any) {
      error.value = e.message
    }
  }

  async function loadModels(provider: string) {
    if (modelsByProvider.value[provider]) return
    try {
      const data = await fetchModels(provider)
      modelsByProvider.value[provider] = data.models
      if (provider === selectedProvider.value && data.models.length > 0) {
        selectedModel.value = data.models[0]
      }
    } catch (e: any) {
      console.warn('Could not load models for', provider, e.message)
    }
  }

  async function execute(request: string) {
    executing.value = true
    progressSteps.value = []
    result.value = null
    error.value = null

    try {
      const finalResult = await executeViaWebSocket(
        request,
        selectedProvider.value,
        selectedModel.value,
        (msg: ProgressMessage) => {
          progressSteps.value.push({
            state: msg.state,
            agent_name: msg.agent_name,
            duration_ms: msg.duration_ms,
            tokens: msg.tokens,
            from_cache: msg.from_cache,
            model_used: msg.model_used,
            revision_count: msg.revision_count,
          })
        },
      )
      result.value = finalResult
      // Refrescar historial automaticamente al completar
      await loadHistory()
    } catch (e: any) {
      error.value = e.message
    } finally {
      executing.value = false
    }
  }

  async function loadHistory() {
    historyLoading.value = true
    try {
      history.value = await fetchExecutions(20)
    } catch (e: any) {
      console.warn('Could not load history:', e.message)
    } finally {
      historyLoading.value = false
    }
  }

  async function viewExecution(id: string) {
    try {
      const detail = await fetchExecutionDetail(id)
      // Reconstituir un FinalOutput-like desde el detalle de la DB
      result.value = detail.final_output
        ? {
            ...detail.final_output,
            agent_traces: detail.traces,
            errors: detail.errors,
            // Enriquecer metadata si no esta en final_output
            metadata: detail.final_output.metadata ?? {
              total_tokens: detail.total_tokens,
              total_duration_ms: detail.duration_ms,
              revisions_performed: detail.revision_count,
            },
            overall_confidence: detail.overall_confidence,
          }
        : null
      progressSteps.value = []
      error.value = null
    } catch (e: any) {
      error.value = e.message
    }
  }

  return {
    // State
    providers,
    selectedProvider,
    selectedModel,
    modelsByProvider,
    executing,
    progressSteps,
    result,
    error,
    history,
    historyLoading,
    // Actions
    loadProviders,
    loadModels,
    execute,
    loadHistory,
    viewExecution,
  }
})
