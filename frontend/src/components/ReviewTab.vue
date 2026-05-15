<template>
  <div class="review-tab">
    <div class="review-header">
      <Tag
        :value="review.approved ? 'Aprobado' : 'Rechazado'"
        :severity="review.approved ? 'success' : 'warn'"
        class="review-badge"
      />
      <div class="confidence-bar">
        <span>Confianza: {{ (review.confidence * 100).toFixed(0) }}%</span>
        <ProgressBar :value="review.confidence * 100" class="conf-progress" />
      </div>
    </div>

    <div class="review-columns">
      <div class="review-col review-col--strengths">
        <h4><i class="pi pi-check-circle" /> Fortalezas</h4>
        <ul>
          <li v-for="s in review.strengths" :key="s">{{ s }}</li>
        </ul>
      </div>
      <div class="review-col review-col--weaknesses">
        <h4><i class="pi pi-times-circle" /> Debilidades</h4>
        <ul>
          <li v-for="w in review.weaknesses" :key="w">{{ w }}</li>
        </ul>
      </div>
      <div class="review-col review-col--suggestions">
        <h4><i class="pi pi-lightbulb" /> Sugerencias</h4>
        <ul>
          <li v-for="s in review.suggestions" :key="s">{{ s }}</li>
        </ul>
      </div>
    </div>

    <div v-if="review.reasoning" class="reasoning">
      <h4>Razonamiento</h4>
      <p>{{ review.reasoning }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import Tag from 'primevue/tag'
import ProgressBar from 'primevue/progressbar'
defineProps<{ review: any }>()
</script>
