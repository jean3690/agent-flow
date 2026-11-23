import 'reflect-metadata';
import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';
import { AuthService } from './auth/auth.service';
import { config } from './config';
import { bootstrapDatabase } from './database/data-source';

async function bootstrap(): Promise<void> {
  process.env.TZ = 'Asia/Shanghai';
  await bootstrapDatabase();
  const app = await NestFactory.create(AppModule, { logger: ['error', 'warn', 'log'] });
  const auth = app.get(AuthService);
  const excluded = new Set(['/api/auth/login', '/api/auth/refresh', '/api/auth/current', '/api/node-types']);
  app.use((req: any, res: any, next: () => void) => {
    if (req.method === 'OPTIONS') return next();
    const requestPath = (req.path || req.url || '').split('?')[0];
    if (!requestPath.startsWith('/api/') || excluded.has(requestPath)) return next();
    const header = req.headers?.authorization;
    let token = header && header.startsWith('Bearer ') ? header.slice(7) : null;
    if (!token) token = req.query?.token;
    if (!token || !auth.validate(String(token))) {
      res.status(401).json({ code: 401, message: '未认证或认证已过期' });
      return;
    }
    next();
  });
  app.enableCors({
    origin: [
      'http://localhost:5173',
      'http://127.0.0.1:5173',
      'http://localhost:5174',
      'http://127.0.0.1:5174',
      /^http:\/\/localhost:\d+$/,
      /^http:\/\/127\.0\.0\.1:\d+$/,
    ],
    methods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
    credentials: true,
  });
  await app.listen(config.port);
  console.log(`[AgentFlow TS] listening on http://localhost:${config.port} (db=${config.dbType})`);
}

bootstrap().catch((error) => {
  console.error('[AgentFlow TS] startup failed:', error);
  process.exit(1);
});
