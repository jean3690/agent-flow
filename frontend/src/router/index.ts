import { createRouter, createWebHashHistory } from 'vue-router'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('../pages/LoginPage.vue'), meta: { public: true } },
    { path: '/', name: 'workflows', component: () => import('../pages/WorkflowListPage.vue') },
    { path: '/editor/:id', name: 'editor', component: () => import('../pages/EditorPage.vue') },
    { path: '/providers', name: 'providers', component: () => import('../pages/ProvidersPage.vue') },
    { path: '/skills', name: 'skills', component: () => import('../pages/SkillsPage.vue') },
    { path: '/mcp', name: 'mcp', component: () => import('../pages/McpPage.vue') },
    { path: '/knowledge', name: 'knowledge', component: () => import('../pages/KnowledgePage.vue') },
    { path: '/memories', name: 'memories', component: () => import('../pages/MemoriesPage.vue') },
    { path: '/approvals', name: 'approvals', component: () => import('../pages/ApprovalsPage.vue') },
    { path: '/executions', name: 'executions', component: () => import('../pages/ExecutionsPage.vue') },
    { path: '/files', name: 'files', component: () => import('../pages/FilesPage.vue') },
    { path: '/live-translation', name: 'live-translation', component: () => import('../pages/LiveTranslationPage.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' }
  ]
})

router.beforeEach((to) => {
  const token = localStorage.getItem('agentflow_token')
  if (!to.meta.public && !token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && token) {
    return { name: 'workflows' }
  }
  return true
})

export default router
