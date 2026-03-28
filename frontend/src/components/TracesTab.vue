<template>
  <div class="traces-tab">
    <DataTable :value="traces" class="traces-table" striped-rows>
      <Column field="agent_name" header="Agente" style="width: 130px" />
      <Column field="state" header="Estado" style="width: 120px" />
      <Column header="Modelo" style="width: 140px">
        <template #body="{ data }">
          <span class="model-pill">{{ data.model_used || '—' }}</span>
        </template>
      </Column>
      <Column header="Duración" style="width: 100px">
        <template #body="{ data }">
          {{ data.duration_ms != null ? data.duration_ms.toFixed(0) + 'ms' : '—' }}
        </template>
      </Column>
      <Column header="Tokens" style="width: 90px">
        <template #body="{ data }">
          {{ ((data.token_usage?.total_tokens ?? data.tokens_in + data.tokens_out) || 0).toLocaleString() }}
        </template>
      </Column>
      <Column header="Cache" style="width: 70px">
        <template #body="{ data }">
          <Tag
            v-if="data.token_usage?.cached || data.from_cache"
            value="hit"
            severity="success"
          />
          <span v-else class="dim">—</span>
        </template>
      </Column>
    </DataTable>
  </div>
</template>

<script setup lang="ts">
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'
import Tag from 'primevue/tag'
defineProps<{ traces: any[] }>()
</script>
