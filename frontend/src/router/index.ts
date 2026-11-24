import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('../pages/LoginPage.vue') },
    { path: '/editor', component: () => import('../pages/EditorPage.vue') },
    { path: '/editor/:id', component: () => import('../pages/EditorPage.vue') },
    { path: '/knowledge', component: () => import('../pages/KnowledgePage.vue') },
    { path: '/mcp-tools', component: () => import('../pages/McpToolPage.vue') },
    { path: '/', redirect: '/editor' },
    { path: '/:pathMatch(.*)*', redirect: '/editor' },
  ],
})

export default router
