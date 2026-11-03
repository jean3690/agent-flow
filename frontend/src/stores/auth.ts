import { defineStore } from 'pinia'
import { ref } from 'vue'
import { authApi } from '../api'
import { TOKEN_KEY } from '../api/request'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem(TOKEN_KEY) || '')
  const user = ref<any>(null)

  async function login(username: string, password: string) {
    const result = await authApi.login(username, password)
    token.value = result.token
    user.value = result.user
    localStorage.setItem(TOKEN_KEY, result.token)
    localStorage.setItem('agentflow_user', JSON.stringify(result.user))
  }

  async function loadUser() {
    if (!token.value) return null
    const cached = localStorage.getItem('agentflow_user')
    if (cached) {
      try {
        user.value = JSON.parse(cached)
      } catch {
        user.value = null
      }
    }
    user.value = await authApi.me()
    localStorage.setItem('agentflow_user', JSON.stringify(user.value))
    return user.value
  }

  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem('agentflow_user')
  }

  return { token, user, login, loadUser, logout }
})
