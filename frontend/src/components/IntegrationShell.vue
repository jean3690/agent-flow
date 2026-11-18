<template>
  <div class="integration">
    <header class="integration__bar">
      <el-button link @click="router.push('/')">← 工作流</el-button>
      <strong>AgentFlow</strong>
      <nav aria-label="扩展配置">
        <router-link to="/knowledge">知识库</router-link>
        <router-link to="/memories">记忆</router-link>
        <router-link to="/skills">Skills</router-link>
        <router-link to="/mcp">MCP</router-link>
      </nav>
    </header>
    <main class="integration__main">
      <div class="integration__heading"><div><h1>{{ title }}</h1><p class="af-muted">{{ description }}</p></div><slot name="actions" /></div>
      <slot />
    </main>
  </div>
</template>
<script setup lang="ts">
import { useRouter } from 'vue-router'
defineProps<{ title: string; description: string }>()
const router = useRouter()
</script>
<style>
.integration { height:100%; overflow:auto; background:#10131a; }
.integration__bar { display:flex; align-items:center; gap:18px; padding:12px 24px; border-bottom:1px solid #262a36; }
.integration__bar nav { display:flex; gap:20px; margin-left:auto; }
.integration__bar a { color:#8b93a7; text-decoration:none; padding:6px 0; }
.integration__bar a.router-link-active { color:#a5b4fc; border-bottom:2px solid #818cf8; }
.integration__main { max-width:1240px; margin:auto; padding:28px 24px; }
.integration__heading { display:flex; align-items:center; justify-content:space-between; gap:16px; margin-bottom:24px; }
.integration__heading h1 { font-size:24px; margin:0 0 8px; }
.integration__heading p { margin:0; line-height:1.6; }
.integration__split { display:grid; grid-template-columns:280px minmax(0,1fr); gap:20px; }
.integration__list, .integration__editor { border:1px solid #262a36; background:#12151d; border-radius:8px; padding:18px; min-width:0; }
.integration__item { display:block; width:100%; text-align:left; padding:12px; margin-bottom:8px; color:#d5dae6; background:#171a23; border:1px solid #262a36; border-radius:6px; cursor:pointer; }
.integration__item.is-selected { border-color:#818cf8; background:#1e2238; }
.integration__item small { display:block; margin-top:6px; color:#8b93a7; overflow-wrap:anywhere; }
.integration__manifest { display:flex; gap:12px; align-items:center; border-bottom:1px solid #262a36; padding-bottom:14px; margin-bottom:18px; }
.integration__manifest code { color:#a5b4fc; font-size:12px; overflow-wrap:anywhere; }
.integration__actions { display:flex; gap:8px; flex-wrap:wrap; margin-top:16px; }
.integration__code textarea, .integration__preview { font-family:ui-monospace,SFMono-Regular,Consolas,monospace; font-size:12px; line-height:1.65; }
.integration__preview { white-space:pre-wrap; overflow-wrap:anywhere; max-height:65vh; overflow:auto; }
.integration__empty { color:#8b93a7; line-height:1.8; padding:20px 0; }
@media(max-width:760px) { .integration__split { grid-template-columns:1fr; } .integration__heading { align-items:flex-start; flex-direction:column; } .integration__main { padding:20px 14px; } }
</style>
