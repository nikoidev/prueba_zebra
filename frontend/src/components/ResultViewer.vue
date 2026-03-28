<template>
  <div class="result-viewer">
    <!-- Métricas globales -->
    <div class="result-metrics">
      <div class="metric">
        <span class="metric-label">Confianza</span>
        <span class="metric-value" :class="confidenceClass">
          {{ (result.overall_confidence * 100).toFixed(0) }}%
        </span>
      </div>
      <div class="metric">
        <span class="metric-label">Tokens</span>
        <span class="metric-value">{{ result.metadata?.total_tokens?.toLocaleString() ?? '—' }}</span>
      </div>
      <div class="metric">
        <span class="metric-label">Duración</span>
        <span class="metric-value">{{ durationLabel }}</span>
      </div>
      <div class="metric">
        <span class="metric-label">Revisiones</span>
        <span class="metric-value">{{ result.metadata?.revisions_performed ?? 0 }}</span>
      </div>
      <div class="metric">
        <span class="metric-label">Cache hits</span>
        <span class="metric-value">{{ result.metadata?.cached_calls ?? 0 }}</span>
      </div>
    </div>

    <p class="result-request">{{ result.original_request }}</p>

    <!-- Tabs -->
    <Tabs value="solution">
      <TabList>
        <Tab value="solution"><i class="pi pi-sitemap" /> Solución</Tab>
        <Tab value="domains"><i class="pi pi-th-large" /> Dominios</Tab>
        <Tab value="review"><i class="pi pi-star" /> Revisión</Tab>
        <Tab value="risks" v-if="result.risk_assessment">
          <i class="pi pi-exclamation-triangle" /> Riesgos
        </Tab>
        <Tab value="traces"><i class="pi pi-list" /> Trazas</Tab>
      </TabList>
      <TabPanels>
        <TabPanel value="solution">
          <SolutionTab :solution="result.solution" />
        </TabPanel>
        <TabPanel value="domains">
          <DomainAnalysisTab :domain-analyses="result.domain_analyses" />
        </TabPanel>
        <TabPanel value="review">
          <ReviewTab :review="result.review" />
        </TabPanel>
        <TabPanel value="risks" v-if="result.risk_assessment">
          <RiskTab :risk-assessment="result.risk_assessment" />
        </TabPanel>
        <TabPanel value="traces">
          <TracesTab :traces="result.agent_traces ?? []" />
        </TabPanel>
      </TabPanels>
    </Tabs>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Tabs from 'primevue/tabs'
import TabList from 'primevue/tablist'
import Tab from 'primevue/tab'
import TabPanels from 'primevue/tabpanels'
import TabPanel from 'primevue/tabpanel'
import SolutionTab from './SolutionTab.vue'
import DomainAnalysisTab from './DomainAnalysisTab.vue'
import ReviewTab from './ReviewTab.vue'
import RiskTab from './RiskTab.vue'
import TracesTab from './TracesTab.vue'

const props = defineProps<{ result: any }>()

const confidenceClass = computed(() => {
  const c = props.result.overall_confidence ?? 0
  if (c >= 0.8) return 'conf-high'
  if (c >= 0.6) return 'conf-mid'
  return 'conf-low'
})

const durationLabel = computed(() => {
  const ms = props.result.metadata?.total_duration_ms
  if (!ms) return '—'
  return ms >= 60000 ? `${(ms / 60000).toFixed(1)}min` : `${(ms / 1000).toFixed(1)}s`
})
</script>
