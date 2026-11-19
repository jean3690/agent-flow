<template>
  <div class="live-page">
    <header class="live-page__bar">
      <el-button link @click="router.push('/')">← 工作流</el-button>
      <span>AgentFlow / 实时语音翻译</span>
      <el-button link @click="router.push('/providers')">模型配置</el-button>
    </header>
    <main class="live-page__main">
      <div class="live-page__heading">
        <div><h1>听见原文，看见译文</h1><p class="af-muted">麦克风语音实时翻译 · {{ config.targetLang.toUpperCase() }} · PCM 16 kHz 输入</p></div>
        <el-tag :type="live.status.value === 'listening' ? 'success' : 'info'">{{ statusText }}</el-tag>
      </div>
      <section class="af-card live-page__controls">
        <el-form label-position="top" :disabled="live.busy.value" class="live-page__form">
          <el-form-item label="翻译服务">
            <el-select v-model="config.provider" aria-label="翻译服务">
              <el-option label="阿里百炼（真实翻译）" value="qwen" />
              <el-option label="Mock（仅验证链路）" value="mock" />
            </el-select>
          </el-form-item>
          <el-form-item label="目标语种">
            <el-select v-model="config.targetLang" filterable aria-label="目标语种">
              <el-option v-for="language in languages" :key="language.value" v-bind="language" />
            </el-select>
          </el-form-item>
          <el-form-item label="业务空间 API Host" class="live-page__host">
            <el-input v-model="config.apiHost" placeholder="<WorkspaceId>.cn-beijing.maas.aliyuncs.com" />
          </el-form-item>
          <el-form-item label="译音播放"><el-switch v-model="config.outputAudio" aria-label="译音播放" /></el-form-item>
        </el-form>
        <p class="live-page__hint">源语种自动识别。Host 不含协议和路径，留空使用服务端配置。语音会发送到百炼；请戴耳机，避免译音被麦克风再次收录。</p>
        <div class="live-page__actions">
          <el-button type="primary" :disabled="live.busy.value" @click="live.start(config)">开始翻译</el-button>
          <el-button :disabled="live.status.value !== 'listening'" @click="live.finish()">结束并收尾</el-button>
          <el-button v-if="live.busy.value" link type="danger" @click="live.cancel()">取消</el-button>
          <span class="af-muted">单次最多 10 分钟 · Key 不发送到浏览器</span>
        </div>
      </section>
      <el-alert v-if="live.mock.value" title="当前为模拟模式：不识别语音，不生成真实译文或译音" type="warning" :closable="false" />
      <el-alert v-if="live.error.value" :title="live.error.value" type="error" :closable="false" role="alert" />
      <div class="live-page__channels" aria-live="polite">
        <section class="af-card live-page__channel">
          <h2><span class="live-page__channel-mark">原</span>原文识别</h2>
          <p v-if="!live.originals.value.length" class="live-page__empty">点击“开始翻译”，允许麦克风后说话。原文会逐段显示在这里。</p>
          <p v-for="caption in live.originals.value" :key="caption.id" :class="{ 'live-page__draft': !caption.done }">{{ caption.text }}</p>
        </section>
        <section class="af-card live-page__channel live-page__channel--translated">
          <h2><span class="live-page__channel-mark">译</span>实时译文</h2>
          <p v-if="!live.translations.value.length" class="live-page__empty">译文会随语音逐段出现。结束录音后，会继续接收剩余结果。</p>
          <p v-for="caption in live.translations.value" :key="caption.id" :class="{ 'live-page__draft': !caption.done }">{{ caption.text }}</p>
        </section>
      </div>
      <p class="af-muted live-page__footer">qwen3.8-livetranslate-flash-realtime <span v-if="live.usage.value.total_tokens">· 累计 {{ live.usage.value.total_tokens }} tokens</span></p>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { useLiveTranslation, type LiveConfig } from '../composables/useLiveTranslation'

const router = useRouter()
const live = useLiveTranslation()
const config = reactive<LiveConfig>({ provider: 'qwen', targetLang: 'en', apiHost: '', outputAudio: true })
const labels = { idle: '未开始', connecting: '正在连接', listening: '正在翻译', finishing: '等待最终结果', finished: '已结束', error: '翻译失败' }
const statusText = computed(() => labels[live.status.value])
const languages = [
  { label: '英语', value: 'en' }, { label: '中文', value: 'zh' }, { label: '日语', value: 'ja' },
  { label: '韩语', value: 'ko' }, { label: '法语', value: 'fr' }, { label: '德语', value: 'de' },
  { label: '西班牙语', value: 'es' }, { label: '俄语', value: 'ru' }, { label: '葡萄牙语', value: 'pt' },
  { label: '意大利语', value: 'it' }, { label: '阿拉伯语', value: 'ar' }
]
</script>

<style scoped>
.live-page { height: 100%; overflow: auto; }
.live-page__bar { display: flex; align-items: center; gap: 20px; height: 54px; padding: 0 28px; border-bottom: 1px solid #262a36; }
.live-page__bar > span { flex: 1; font-size: 13px; }
.live-page__main { max-width: 1240px; margin: auto; padding: 32px 28px; }
.live-page__heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; gap: 16px; }
.live-page__heading h1 { font-size: 28px; font-weight: 600; letter-spacing: .04em; margin: 0 0 8px; }
.live-page__controls { padding: 22px; margin-bottom: 20px; }
.live-page__form { display: grid; grid-template-columns: 190px 140px minmax(220px, 1fr) 100px; gap: 18px; }
.live-page__hint { color: #9ca5b8; font-size: 12px; line-height: 1.8; margin: 0 0 18px; }
.live-page__actions { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.live-page__actions > span { margin-left: auto; font-size: 12px; }
.live-page__channels { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-top: 20px; }
.live-page__channel { padding: 24px; min-height: 340px; }
.live-page__channel h2 { display: flex; align-items: center; gap: 12px; font-size: 15px; margin: 0 0 26px; }
.live-page__channel-mark { display: grid; place-items: center; width: 30px; height: 30px; color: #a8b3c9; border: 1px solid #48536a; border-radius: 6px; }
.live-page__channel--translated .live-page__channel-mark { color: #56c8d8; border-color: #377a86; }
.live-page__channel > p { font-size: 17px; line-height: 1.9; white-space: pre-wrap; overflow-wrap: anywhere; }
.live-page__channel > .live-page__empty { color: #8691a8; font-size: 14px; max-width: 30em; }
.live-page__draft { color: #a8b3c9; border-left: 2px solid #56c8d8; padding-left: 12px; }
.live-page__footer { font-size: 12px; margin-top: 20px; }
@media (max-width: 900px) { .live-page__form { grid-template-columns: 1fr 1fr; } .live-page__host { grid-column: 1 / -1; } }
@media (max-width: 600px) { .live-page__main { padding: 24px 16px; } .live-page__channels { grid-template-columns: 1fr; } .live-page__heading h1 { font-size: 22px; } .live-page__actions > span { width: 100%; margin: 0; } }
</style>
