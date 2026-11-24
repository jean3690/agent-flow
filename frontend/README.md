# AgentFlow Frontend

AI Agent 流图执行面板前端项目

## 技术栈

- Vue 3
- TypeScript
- Vite
- Vue Flow (流程图编辑器)
- Ant Design Vue (UI 组件库)
- Tailwind CSS (样式框架)
- Pinia (状态管理)
- Axios (HTTP 客户端)
- Vue Router (路由管理)

## 快速开始

### 1. 安装依赖

```bash
npm install
```

### 2. 启动开发服务器

```bash
cp .env.example .env.local
npm run dev
```

应用将在 http://localhost:5173 启动

默认会连接 `http://localhost:8084` 后端。如果后端地址有变化，修改 `frontend/.env.local`：

```bash
VITE_API_BASE_URL=http://localhost:8084
```

### 3. 构建生产版本

```bash
npm run build
```

构建产物做了体积优化：页面按路由动态 import 懒加载，Ant Design Vue 组件按需自动引入（unplugin-vue-components），Vue / Vue Flow 单独分包，调试抽屉按需加载。Nginx 配置已开启 gzip 压缩。

## 项目结构

```
src/
├── api/              # API 接口
├── pages/            # 页面组件
├── components/       # 可复用组件
├── router/           # 路由配置
├── stores/           # Pinia 状态管理
├── utils/            # 工具函数
├── App.vue           # 根组件
└── main.ts           # 入口文件
```

## 功能特性

- ✅ 用户登录/登出
- ✅ 路由守卫
- ✅ 认证状态管理
- ✅ API 请求封装
- ✅ 工作流编辑器（Vue Flow）
- ✅ 节点面板与节点配置
- ✅ 调试抽屉（SSE 实时执行）
- ✅ 知识库与 MCP 工具管理

## 环境变量

后端 API 地址通过 Vite 环境变量配置，示例见 `.env.example`：

```bash
VITE_API_BASE_URL=http://localhost:8084
```

## 默认账户

- 用户名: admin
- 密码: 123
