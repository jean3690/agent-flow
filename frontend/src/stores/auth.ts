import { defineStore } from 'pinia'
import { ref } from 'vue'
import { clearStoredAuth, getAccessToken, getRefreshToken, getUsername, setStoredAuth } from '../utils/auth'

/**
 * 认证状态管理
 */
export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(getAccessToken())
  const refreshToken = ref<string | null>(getRefreshToken())
  const username = ref<string | null>(getUsername())
  const isAuthenticated = ref<boolean>(!!getRefreshToken())

  const setAuth = (nextToken: string, nextRefreshToken: string, nextUsername: string) => {
    setStoredAuth(nextToken, nextRefreshToken, nextUsername)
    token.value = nextToken
    refreshToken.value = nextRefreshToken
    username.value = nextUsername
    isAuthenticated.value = true
  }

  const clearAuth = () => {
    clearStoredAuth()
    token.value = null
    refreshToken.value = null
    username.value = null
    isAuthenticated.value = false
  }

  return { token, refreshToken, username, isAuthenticated, setAuth, clearAuth }
})
