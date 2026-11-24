<template>
  <a-spin :spinning="loading">
    <a-select
      v-model:value="model"
      :disabled="disabled"
      placeholder="选择一个技能（可选）"
      allow-clear
      style="width: 100%"
    >
      <template #suffixIcon>
        <BookOutlined />
      </template>
      <a-select-option v-for="skill in skills" :key="skill.name" :value="skill.name">
        <a-tooltip :title="skill.description" placement="right">
          <div class="flex items-center gap-2">
            <a-tag color="blue">{{ skill.name }}</a-tag>
            <span class="text-gray-500 text-xs truncate max-w-48">
              {{ skill.description }}
            </span>
          </div>
        </a-tooltip>
      </a-select-option>
    </a-select>
  </a-spin>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { BookOutlined } from '@ant-design/icons-vue'
import { getSkills, type SkillSummary } from '../api/skill'

defineProps<{ disabled?: boolean }>()

const model = defineModel<string | undefined>()

const skills = ref<SkillSummary[]>([])
const loading = ref(false)

const loadSkills = async () => {
  loading.value = true
  try {
    const response = await getSkills()
    if (response.code === 200 && response.data) {
      skills.value = response.data
    }
  } catch (error) {
    console.error('Failed to load skills:', error)
  } finally {
    loading.value = false
  }
}

onMounted(loadSkills)
</script>
