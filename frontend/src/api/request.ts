import axios from 'axios'
import { ElMessage } from 'element-plus'

export const TOKEN_KEY = 'agentflow_token'
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/+$/, '')

const http = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000
})

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    config.headers.Authorization = 'Bearer ' + token
  }
  return config
})

http.interceptors.response.use(
  (response) => {
    const body = response.data
    if (body && typeof body.code === 'number') {
      if (body.code !== 0) {
        ElMessage.error(body.message || '请求失败')
        return Promise.reject(new Error(body.message || '请求失败'))
      }
      return body.data
    }
    return body
  },
  (error) => {
    const status = error.response?.status
    const message = error.response?.data?.message || error.message || '网络异常'
    if (status === 401) {
      localStorage.removeItem(TOKEN_KEY)
      if (!location.hash.includes('/login')) {
        location.hash = '#/login'
      }
    } else {
      ElMessage.error(message)
    }
    return Promise.reject(new Error(message))
  }
)

export default http
