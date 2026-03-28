<template>
  <div class="domain-tab">
    <Accordion :value="openPanels" multiple>
      <AccordionPanel
        v-for="(analysis, key) in domainAnalyses"
        :key="key"
        :value="key"
      >
        <AccordionHeader>
          <span class="domain-header">
            {{ analysis.agent_name || key }}
            <Tag
              :value="`${(analysis.confidence * 100).toFixed(0)}%`"
              :severity="analysis.confidence >= 0.8 ? 'success' : analysis.confidence >= 0.6 ? 'warn' : 'danger'"
              class="conf-tag"
            />
            <Tag v-if="analysis.degraded" value="degraded" severity="danger" />
          </span>
        </AccordionHeader>
        <AccordionContent>
          <div class="domain-content">
            <div class="domain-section">
              <strong>Hallazgos</strong>
              <p>{{ analysis.findings }}</p>
            </div>
            <div v-if="analysis.recommendations?.length" class="domain-section">
              <strong>Recomendaciones</strong>
              <ul>
                <li v-for="r in analysis.recommendations" :key="r">{{ r }}</li>
              </ul>
            </div>
            <div v-if="analysis.assumptions?.length" class="domain-section">
              <strong>Suposiciones</strong>
              <ul class="assumptions">
                <li v-for="a in analysis.assumptions" :key="a">{{ a }}</li>
              </ul>
            </div>
          </div>
        </AccordionContent>
      </AccordionPanel>
    </Accordion>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Accordion from 'primevue/accordion'
import AccordionPanel from 'primevue/accordionpanel'
import AccordionHeader from 'primevue/accordionheader'
import AccordionContent from 'primevue/accordioncontent'
import Tag from 'primevue/tag'

const props = defineProps<{ domainAnalyses: Record<string, any> }>()

const openPanels = computed(() => Object.keys(props.domainAnalyses).slice(0, 1))
</script>
