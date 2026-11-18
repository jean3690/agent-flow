<template>
  <IntegrationShell title="Skills" description="把领域指令挂载到模型。平台共享技能由管理员维护，内置技能只读。">
    <template #actions><div><el-button :loading="loading" @click="load">刷新列表</el-button><el-button v-if="admin" type="primary" @click="create">新建技能</el-button><el-button v-if="admin" @click="fileInput?.click()">导入 SKILL.md</el-button><input ref="fileInput" type="file" accept=".md" hidden @change="importFile" /></div></template>
    <div class="integration__split" v-loading="loading">
      <aside class="integration__list">
        <button v-for="item in skills" :key="item.name" class="integration__item" :class="{ 'is-selected': form.name === item.name }" @click="select(item.name)">
          <strong>{{ item.title }}</strong><small>{{ item.name }} · {{ item.editable ? '自定义' : '内置只读' }}</small><small>{{ item.description }}</small>
        </button>
        <div v-if="!skills.length" class="integration__empty">还没有技能。管理员可新建或导入 SKILL.md，然后在模型节点选择挂载。</div>
      </aside>
      <section class="integration__editor" v-loading="detailLoading">
        <template v-if="active">
          <div class="integration__manifest"><code>SKILL.md / {{ form.name || '新技能' }}</code><el-tag size="small">指令与资料，不执行脚本</el-tag></div>
          <el-form label-position="top" :disabled="saving">
            <el-form-item label="技能标识"><el-input v-model="form.name" :disabled="!!selected || !admin" placeholder="report-helper" /></el-form-item>
            <el-form-item label="SKILL.md 内容"><el-input v-model="form.content" type="textarea" :rows="18" :readonly="!editable" class="integration__code" /></el-form-item>
          </el-form>
          <div v-if="detail?.references.length" class="integration__actions"><el-button v-for="reference in detail.references" :key="reference.file" @click="showReference(reference.file)">{{ reference.file }}</el-button></div>
          <div class="integration__actions"><el-button v-if="editable" type="primary" :loading="saving" @click="save">保存技能</el-button><el-button v-if="admin && detail?.editable" type="danger" plain @click="remove">删除技能</el-button><el-button v-if="admin && detail && !detail.editable" @click="copy">复制为自定义技能</el-button></div>
        </template>
        <div v-else class="integration__empty">选择一个技能查看正文与引用资料。</div>
      </section>
    </div>
    <el-dialog v-model="referenceOpen" title="引用资料" width="720px"><pre class="integration__preview">{{ referenceText }}</pre></el-dialog>
  </IntegrationShell>
</template>
<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import IntegrationShell from '../components/IntegrationShell.vue'
import { skillApi } from '../api'
import { useAuthStore } from '../stores/auth'
import type { SkillSummary, SkillDetail } from '../types'
const auth = useAuthStore()
const admin = computed(() => auth.user?.role === 'ADMIN')
const skills = ref<SkillSummary[]>([])
const detail = ref<SkillDetail | null>(null)
const loading = ref(false), saving = ref(false), detailLoading = ref(false), active = ref(false)
const selected = ref('')
const editable = computed(() => admin.value && (!detail.value || detail.value.editable))
const form = reactive({ name: '', content: '' })
const fileInput = ref<HTMLInputElement | null>(null)
const referenceOpen = ref(false), referenceText = ref('')
let requestId = 0
const initial = ref('')
const dirty = computed(() => active.value && initial.value !== JSON.stringify(form))
async function discard() {
  if (saving.value || detailLoading.value) return false
  if (!dirty.value) return true
  try { await ElMessageBox.confirm('未保存的技能修改将丢失，继续？', '未保存修改', { type:'warning' }); return true } catch { return false }
}
onBeforeRouteLeave(discard)
async function load() { loading.value = true; try { skills.value = await skillApi.list() } finally { loading.value = false } }
async function select(name: string) {
  if (!(await discard())) return
  const id = ++requestId; detailLoading.value = true
  try { const result = await skillApi.detail(name); if (id !== requestId) return; detail.value = result; selected.value = name; Object.assign(form, { name, content:result.rawContent }); initial.value = JSON.stringify(form); active.value = true } finally { if (id === requestId) detailLoading.value = false }
}
async function create() {
  if (!(await discard())) return
  ++requestId; detail.value = null; selected.value = ''; active.value = true
  Object.assign(form, { name:'report-helper', content:'---\nname: report-helper\ntitle: 报告助手\ndescription: 组织清晰、可核查的报告\nversion: 1.0.0\ntags: [报告]\n---\n\n先明确问题与资料，再分章节给出结论。不得编造数据。\n' }); initial.value = JSON.stringify(form)
}
watch(() => form.name, (name, previous) => { if (!selected.value && form.content.startsWith('---') && form.content.includes('name: ' + previous + '\n')) form.content = form.content.replace('name: ' + previous + '\n', 'name: ' + name + '\n') })
async function save() {
  if (!/^[a-z][a-z0-9_-]{0,63}$/.test(form.name)) { ElMessage.warning('请输入有效的小写技能标识'); return }
  saving.value = true
  const snapshot = JSON.stringify(form), payload = JSON.parse(snapshot)
  try { detail.value = await skillApi.save(payload.name, payload.content); selected.value = payload.name; initial.value = snapshot; ElMessage.success('技能已保存'); await load() } finally { saving.value = false }
}
async function remove() { if (!detail.value) return; try { await ElMessageBox.confirm('删除后，引用此技能的工作流需重新配置。确定删除？', '删除技能', { type:'warning' }) } catch { return }; await skillApi.remove(detail.value.name); active.value = false; detail.value = null; await load() }
async function copy() { if (!detail.value || !(await discard())) return; const current = detail.value; detail.value = null; selected.value = ''; active.value = true; Object.assign(form, { name:current.name + '-copy', content:current.rawContent.replace(/^name:.*$/m, 'name: ' + current.name + '-copy') }); initial.value = JSON.stringify(form) }
async function importFile(event: Event) { const input = event.target as HTMLInputElement; const file = input.files?.[0]; input.value = ''; if (!file || !(await discard())) return; const content = await file.text(); if (content.length > 200000) { ElMessage.warning('文件过大'); return }; detail.value = null; selected.value = ''; active.value = true; Object.assign(form, { name:content.match(/^name:\s*['"]?([a-z][a-z0-9_-]*)['"]?\s*$/m)?.[1] || '', content }); initial.value = ''; }
async function showReference(file: string) { referenceText.value = (await skillApi.reference(selected.value, file)).content; referenceOpen.value = true }
onMounted(async () => { await auth.loadUser(); await load() })
</script>
