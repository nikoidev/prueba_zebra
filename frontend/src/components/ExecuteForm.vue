<template>
  <div class="execute-form">
    <h2 class="form-title">🦓 Zebra — Multi-Agent System</h2>

    <div class="field">
      <label>Solicitud</label>
      <Textarea
        v-model="requestText"
        :rows="5"
        placeholder="Describe el sistema, plataforma o problema que quieres analizar..."
        :disabled="store.executing"
        auto-resize
        class="w-full"
      />
    </div>

    <div class="field-row">
      <div class="field">
        <label>Proveedor</label>
        <Select
          v-model="store.selectedProvider"
          :options="store.providers"
          :disabled="store.executing"
          class="w-full"
          @change="onProviderChange"
        />
      </div>
      <div class="field">
        <label>Modelo</label>
        <Select
          v-model="store.selectedModel"
          :options="currentModels"
          :disabled="store.executing || currentModels.length === 0"
          :loading="loadingModels"
          class="w-full"
        />
      </div>
    </div>

    <Button
      label="Ejecutar pipeline"
      icon="pi pi-play"
      :loading="store.executing"
      :disabled="!requestText.trim() || store.executing"
      class="w-full execute-btn"
      @click="onExecute"
    />

    <div v-if="store.error" class="error-msg">
      <i class="pi pi-exclamation-triangle" />
      {{ store.error }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import Textarea from 'primevue/textarea'
import Select from 'primevue/select'
import Button from 'primevue/button'
import { usePipelineStore } from '../stores/pipeline'

const store = usePipelineStore()
const requestText = ref('')
const loadingModels = ref(false)

const currentModels = computed(
  () => store.modelsByProvider[store.selectedProvider] ?? []
)

async function onProviderChange() {
  if (!store.modelsByProvider[store.selectedProvider]) {
    loadingModels.value = true
    await store.loadModels(store.selectedProvider)
    loadingModels.value = false
  }
  const models = store.modelsByProvider[store.selectedProvider]
  if (models?.length) store.selectedModel = models[0]
}

async function onExecute() {
  if (!requestText.value.trim()) return
  await store.execute(requestText.value.trim())
}
</script>
