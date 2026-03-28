<template>
  <div class="solution-tab">
    <p class="solution-summary">{{ solution.summary }}</p>

    <h4>Componentes</h4>
    <div class="components-grid">
      <div v-for="comp in solution.components" :key="comp.name" class="component-card">
        <div class="comp-header">
          <span class="comp-name">{{ comp.name }}</span>
          <Tag :value="comp.technology" severity="info" />
        </div>
        <p class="comp-desc">{{ comp.description }}</p>
        <ul class="comp-resp">
          <li v-for="r in comp.responsibilities" :key="r">{{ r }}</li>
        </ul>
      </div>
    </div>

    <div v-if="solution.integration_notes" class="section">
      <h4>Notas de integración</h4>
      <p>{{ solution.integration_notes }}</p>
    </div>

    <div v-if="solution.tech_decisions?.length" class="section">
      <h4>Decisiones técnicas</h4>
      <ul class="decisions">
        <li v-for="d in solution.tech_decisions" :key="d">{{ d }}</li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
import Tag from 'primevue/tag'
defineProps<{ solution: any }>()
</script>
