<template>
  <div class="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 to-indigo-100">
    <div class="bg-white rounded-lg shadow-xl p-8 w-96">
      <div class="text-center mb-8">
        <h1 class="text-3xl font-bold text-gray-800 mb-2">AgentFlow</h1>
        <p class="text-gray-600">AI Agent 流图执行面板</p>
      </div>

      <a-form :model="formState" name="login" size="large" @finish="onFinish">
        <a-form-item name="username" :rules="[{ required: true, message: '请输入用户名' }]">
          <a-input v-model:value="formState.username" placeholder="用户名">
            <template #prefix><UserOutlined /></template>
          </a-input>
        </a-form-item>

        <a-form-item name="password" :rules="[{ required: true, message: '请输入密码' }]">
          <a-input-password v-model:value="formState.password" placeholder="密码">
            <template #prefix><LockOutlined /></template>
          </a-input-password>
        </a-form-item>

        <a-form-item>
          <a-button type="primary" html-type="submit" class="w-full" :loading="loading">
            登录
          </a-button>
        </a-form-item>
      </a-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { LockOutlined, UserOutlined } from '@ant-design/icons-vue'
import { login } from '../api/auth'
import { useAuthStore } from '../stores/auth'

const loading = ref(false)
const router = useRouter()
const authStore = useAuthStore()

const formState = reactive({
  username: '',
  password: '',
})

const onFinish = async (values: { username: string; password: string }) => {
  loading.value = true
  try {
    const result = await login(values)
    if (result.code === 200 && result.data) {
      message.success('登录成功')
      authStore.setAuth(result.data.token, result.data.refreshToken, result.data.user.username)
      router.push('/')
    } else {
      message.error(result.message || '登录失败')
    }
  } catch {
    message.error('登录失败,请检查网络连接')
  } finally {
    loading.value = false
  }
}
</script>
