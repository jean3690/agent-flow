import { MiddlewareConsumer, Module, NestModule, Injectable } from '@nestjs/common';
import { AuthService } from './auth/auth.service';
import { AuthController } from './auth/auth.controller';
import { LlmService } from './services/llm.service';
import { AgentPlanService } from './services/agent-plan.service';
import { KnowledgeService } from './services/knowledge.service';
import { McpService } from './services/mcp.service';
import { MediaService } from './services/media.service';
import { SkillsService } from './services/skills.service';
import { LlmConfigService } from './services/llm-config.service';
import { ExecutorRegistry } from './engine/executors';
import { EngineService } from './engine/engine.service';
import {
  WorkflowsController,
  ExecutionsController,
  NodeTypesController,
  LlmConfigController,
  SkillsController,
  KnowledgeController,
  McpController,
  MediaController,
} from './modules/controllers';

const EXCLUDED = new Set([
  '/api/auth/login',
  '/api/auth/refresh',
  '/api/auth/current',
  '/api/node-types',
  '/docs',
  '/openapi.json',
]);

@Injectable()
export class AuthMiddleware {
  constructor(private readonly auth: AuthService) {}

  use(req: any, res: any, next: () => void): void {
    if (req.method === 'OPTIONS') return next();
    const path = req.path || '';
    if (!path.startsWith('/api/') || EXCLUDED.has(path)) return next();
    const header = req.headers?.authorization;
    let token = header && header.startsWith('Bearer ') ? header.slice(7) : null;
    if (!token) token = req.query?.token;
    if (!token || !this.auth.validate(String(token))) {
      res.status(401).json({ code: 401, message: '未认证或认证已过期' });
      return;
    }
    next();
  }
}

@Module({
  controllers: [
    AuthController,
    WorkflowsController,
    ExecutionsController,
    NodeTypesController,
    LlmConfigController,
    SkillsController,
    KnowledgeController,
    McpController,
    MediaController,
  ],
  providers: [
    AuthService,
    AuthMiddleware,
    LlmService,
    AgentPlanService,
    KnowledgeService,
    McpService,
    MediaService,
    SkillsService,
    LlmConfigService,
    ExecutorRegistry,
    EngineService,
  ],
})
export class AppModule {}
