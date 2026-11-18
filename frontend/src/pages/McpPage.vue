<template>
  <IntegrationShell title="MCP 服务" description="连接远程工具。先保存服务，再测试连接，最后明确选择允许工作流调用的工具。">
    <template #actions><div><el-button :loading="loading" @click="load">刷新列表</el-button><el-button type="primary" @click="create">添加 MCP 服务</el-button></div></template>
    <div class="integration__split" v-loading="loading">
      <aside class="integration__list">
        <button v-for="item in servers" :key="item.id" class="integration__item" :class="{ 'is-selected': id === item.id }" @click="select(item)"><strong>{{ item.name }}</strong><small>{{ item.enabled ? '启用' : '停用' }} · {{ item.allowedTools.length }} 个授权工具</small><small>{{ item.url }}</small></button>
        <div v-if="!servers.length" class="integration__empty">尚未配置远程工具。添加 Streamable HTTP 服务地址后测试连接。</div>
      </aside>
      <section v-if="active" class="integration__editor">
        <div class="integration__manifest"><code>Streamable HTTP</code><el-tag size="small" :type="hasCredentials ? 'success' : 'info'">{{ hasCredentials ? '认证信息已加密保存' : '未设置认证' }}</el-tag></div>
        <el-form label-position="top" :disabled="saving || testing">
          <el-form-item label="服务名称"><el-input v-model="form.name" placeholder="文档检索服务" /></el-form-item>
          <el-form-item label="MCP 地址"><el-input v-model="form.url" placeholder="https://example.com/mcp" /><div class="af-muted">默认只允许公网地址，不支持 stdio、本地命令或 URL 中的凭据。</div></el-form-item>
          <el-form-item label="认证请求头（JSON）"><el-input v-model="headers" type="textarea" :rows="3" class="integration__code" placeholder='{"Authorization":"Bearer …"}' /><div class="af-muted">留空保留已保存的请求头；更改地址会清除旧地址的凭据。</div></el-form-item>
          <el-form-item v-if="hasCredentials" label="清除已有认证"><el-switch v-model="form.clearHeaders" /></el-form-item>
          <el-form-item label="超时（毫秒）"><el-input-number v-model="form.timeoutMs" :min="1000" :max="60000" :step="1000" /></el-form-item>
          <el-form-item label="启用服务"><el-switch v-model="form.enabled" /></el-form-item>
        </el-form>
        <div class="integration__actions"><el-button type="primary" :loading="saving" :disabled="testing" @click="save">保存配置</el-button><el-button :loading="testing" :disabled="!id || saving" @click="discover">测试连接 / 发现工具</el-button><el-button v-if="id" type="danger" plain :disabled="saving || testing" @click="remove">删除服务</el-button></div>
        <p v-if="message" role="status" :class="{ 'af-muted': ok }">{{ message }}</p>
        <h3>允许调用的工具</h3><p class="af-muted">发现工具不代表授权。勾选并保存后，智能体和 MCP 工具节点才能调用。</p>
        <el-checkbox-group v-model="form.allowedTools" :disabled="saving || testing"><div v-for="tool in tools" :key="tool.name" style="padding:12px 0;border-bottom:1px solid #262a36"><el-checkbox :label="tool.name" :value="tool.name" /><p class="af-muted">{{ tool.description }}</p><el-collapse><el-collapse-item title="查看参数结构" :name="tool.name"><pre class="integration__preview">{{ JSON.stringify(tool.inputSchema, null, 2) }}</pre></el-collapse-item></el-collapse></div></el-checkbox-group>
        <div v-if="!tools.length" class="integration__empty">保存服务后测试连接，查看可用工具。</div>
      </section>
      <section v-else class="integration__editor integration__empty">选择服务查看配置，或添加新的 MCP 服务。</section>
    </div>
  </IntegrationShell>
</template>
<script setup lang="ts">
import { reactive, ref } from 'vue'
import { onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import IntegrationShell from '../components/IntegrationShell.vue'
import { mcpApi } from '../api'
import type { McpServer, McpTool } from '../types'
const servers = ref<McpServer[]>([]), tools = ref<McpTool[]>([])
const id = ref<number | null>(null), active = ref(false), hasCredentials = ref(false)
const loading = ref(false), saving = ref(false), testing = ref(false), headers = ref(''), message = ref(''), ok = ref(true)
const form = reactive({ name:'', url:'', timeoutMs:15000, enabled:true, allowedTools:[] as string[], clearHeaders:false })
let persistedUrl = ''
async function load() { loading.value = true; try { servers.value = await mcpApi.list() } finally { loading.value = false } }
function select(item: McpServer) { id.value = item.id; active.value = true; hasCredentials.value = item.hasCredentials; persistedUrl = item.url; headers.value = ''; message.value = ''; tools.value = item.tools; Object.assign(form, { name:item.name, url:item.url, timeoutMs:item.timeoutMs, enabled:item.enabled, allowedTools:[...item.allowedTools], clearHeaders:false }) }
function create() { id.value = null; active.value = true; hasCredentials.value = false; tools.value = []; headers.value = ''; message.value = ''; persistedUrl = ''; Object.assign(form, { name:'', url:'', timeoutMs:15000, enabled:true, allowedTools:[], clearHeaders:false }) }
async function save() {
  if (!form.name.trim() || !form.url.trim()) { ElMessage.warning('请填写服务名称和地址'); return false }
  let parsed: Record<string,string> | undefined
  try { if (headers.value.trim()) { parsed = JSON.parse(headers.value); if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed) || Object.values(parsed).some(v => typeof v !== 'string')) throw new Error() } } catch { ElMessage.warning('请求头必须是 JSON 字符串键值对象'); return false }
  saving.value = true
  const changed = persistedUrl && persistedUrl !== form.url.trim()
  const payload = { ...form, name:form.name.trim(), url:form.url.trim(), allowedTools:changed ? [] : [...form.allowedTools], headers:parsed }
  try { const result = id.value ? await mcpApi.update(id.value, payload) : await mcpApi.create(payload); select(result); ElMessage.success('MCP 配置已保存'); await load(); return true } finally { saving.value = false }
}
async function discover() { if (!id.value) return; if (!(await save())) return; testing.value = true; try { const result = await mcpApi.discover(id.value!); message.value = result.message; ok.value = result.ok; if (result.ok) { tools.value = result.tools; await load() } } finally { testing.value = false } }
async function remove() { if (!id.value) return; try { await ElMessageBox.confirm('删除后，引用此服务的工作流将无法调用对应工具。确定删除？', '删除 MCP 服务', { type:'warning' }) } catch { return }; await mcpApi.remove(id.value); active.value = false; await load() }
onMounted(load)
</script>
