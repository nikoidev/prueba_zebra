<template>
  <div class="risk-tab">
    <div class="risk-header">
      <span>Nivel de riesgo global:</span>
      <Tag
        :value="riskAssessment.overall_risk_level?.toUpperCase()"
        :severity="riskSeverity(riskAssessment.overall_risk_level)"
        class="risk-global-tag"
      />
    </div>

    <DataTable :value="riskAssessment.risks" class="risk-table" striped-rows>
      <Column field="title" header="Riesgo" style="min-width: 160px" />
      <Column header="Severidad" style="width: 120px">
        <template #body="{ data }">
          <Tag :value="data.severity" :severity="riskSeverity(data.severity)" />
        </template>
      </Column>
      <Column field="category" header="Categoría" style="width: 110px" />
      <Column field="description" header="Descripción" style="min-width: 220px" />
      <Column field="mitigation" header="Mitigación" style="min-width: 200px" />
    </DataTable>

    <div v-if="riskAssessment.regulatory_notes" class="section">
      <h4>Notas regulatorias</h4>
      <p>{{ riskAssessment.regulatory_notes }}</p>
    </div>

    <div v-if="riskAssessment.recommendations?.length" class="section">
      <h4>Recomendaciones</h4>
      <ul>
        <li v-for="r in riskAssessment.recommendations" :key="r">{{ r }}</li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import Tag from 'primevue/tag'
import DataTable from 'primevue/datatable'
import Column from 'primevue/column'

defineProps<{ riskAssessment: any }>()

function riskSeverity(level: string) {
  switch (level?.toLowerCase()) {
    case 'critical': return 'danger'
    case 'high': return 'danger'
    case 'medium': return 'warn'
    case 'low': return 'success'
    default: return 'secondary'
  }
}
</script>
