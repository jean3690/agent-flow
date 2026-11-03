<template>
  <div class="login">
    <div class="login__intro">
      <div class="login__brand">
        <span class="login__logo">AF</span>
        <span>AgentFlow</span>
      </div>
      <h1>把 AI 能力<br />编排成可复用的流程</h1>
      <p>
        LangGraph 负责执行，Java 负责业务与留痕，Vue 负责编排体验。
        拖拽节点、连线、运行，一次配置反复使用。
      </p>
      <ul>
        <li>7 类内置节点，条件分支与流式输出</li>
        <li>模型厂商统一走 OpenAI 兼容协议</li>
        <li>每次执行自动落库，可回放节点级日志</li>
      </ul>
    </div>

    <div class="login__panel">
      <div class="af-card login__card">
        <h2>登录</h2>
        <p class="af-muted">默认账号 admin / admin123</p>
        <el-form label-position="top" @submit.prevent="submit">
          <el-form-item label="用户名">
            <el-input v-model="username" size="large" placeholder="admin" @keyup.enter="submit" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="password" size="large" type="password" show-password placeholder="admin123" @keyup.enter="submit" />
          </el-form-item>
          <el-button type="primary" size="large" class="login__submit" :loading="loading" @click="submit">
            进入工作台
          </el-button>
        </el-form>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'

const authStore = useAuthStore()
const router = useRouter()
const route = useRoute()

const username = ref('admin')
const password = ref('admin123')
const loading = ref(false)

async function submit() {
  if (!username.value || !password.value) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await authStore.login(username.value, password.value)
    const redirect = (route.query.redirect as string) || '/'
    router.replace(redirect)
  } catch {
    // error already surfaced by the interceptor
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login {
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  height: 100%;
}

.login__intro {
  position: relative;
  padding: 64px 7vw;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 18px;
  background:
    radial-gradient(circle at 20% 20%, rgba(99, 102, 241, 0.22), transparent 55%),
    radial-gradient(circle at 80% 70%, rgba(14, 165, 233, 0.15), transparent 50%),
    #0d1017;
  border-right: 1px solid #1e2230;
}

.login__brand {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.login__logo {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: #6366f1;
  font-size: 12px;
  color: white;
}

.login__intro h1 {
  margin: 0;
  font-size: clamp(30px, 3.4vw, 46px);
  line-height: 1.2;
  letter-spacing: -0.02em;
}

.login__intro p {
  max-width: 460px;
  color: #8b93a7;
  line-height: 1.8;
  margin: 0;
}

.login__intro ul {
  margin: 6px 0 0;
  padding-left: 18px;
  color: #6b7387;
  line-height: 2;
  font-size: 13px;
}

.login__panel {
  display: grid;
  place-items: center;
  padding: 32px;
}

.login__card {
  width: min(360px, 100%);
  padding: 30px 28px;
}

.login__card h2 {
  margin: 0 0 4px;
  font-size: 20px;
}

.login__card p {
  margin: 0 0 22px;
  font-size: 12px;
}

.login__submit {
  width: 100%;
  margin-top: 6px;
}

@media (max-width: 900px) {
  .login {
    grid-template-columns: 1fr;
  }
  .login__intro {
    display: none;
  }
}
</style>
