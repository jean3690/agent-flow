import * as dotenv from 'dotenv';
import path from 'path';
import crypto from 'crypto';
import fs from 'fs';

function findRepoDir(start: string): string {
  let current = start;
  for (let i = 0; i < 6; i++) {
    if (fs.existsSync(path.join(current, 'backend', 'src', 'main', 'resources', 'schema.sql'))) return current;
    current = path.dirname(current);
  }
  return path.resolve(start, '..', '..', '..');
}
const repoDir = findRepoDir(__dirname);
dotenv.config({ path: path.resolve(__dirname, '..', '.env') });
dotenv.config({ path: path.join(repoDir, 'backend', '.env') });

function intEnv(name: string, fallback: number): number {
  const value = Number(process.env[name]);
  return Number.isFinite(value) && value ? Math.trunc(value) : fallback;
}

export const config = {
  port: intEnv('SERVER_PORT', 8084),
  dbType: (process.env.DB_TYPE || 'mysql') as 'mysql' | 'sqljs',
  mysqlHost: process.env.MYSQL_HOST || 'localhost',
  mysqlPort: intEnv('MYSQL_PORT', 3306),
  mysqlDatabase: process.env.MYSQL_DATABASE || 'agent_flow',
  mysqlUsername: process.env.MYSQL_USERNAME || 'root',
  mysqlPassword: process.env.MYSQL_PASSWORD || '',
  sqlitePath: process.env.AGENTFLOW_DATABASE_URL?.replace(/^sqlite:\/\//, '') || path.join(repoDir, 'ts-backend', 'ts-smoke.db'),
  autoMigrate: (process.env.AGENTFLOW_AUTO_MIGRATE || 'true') !== 'false',
  schemaSqlPath: process.env.AGENTFLOW_SCHEMA_SQL || path.join(repoDir, 'backend', 'src', 'main', 'resources', 'schema.sql'),
  redisHost: process.env.REDIS_HOST || 'localhost',
  redisPort: intEnv('REDIS_PORT', 6379),
  redisPassword: process.env.REDIS_PASSWORD || '',
  jwtSecretConfigured: (process.env.JWT_SECRET || '').trim(),
  accessTokenMinutes: intEnv('ACCESS_TOKEN_EXPIRATION_MINUTES', 120),
  refreshTokenHours: intEnv('REFRESH_TOKEN_EXPIRATION_HOURS', 168),
  defaultUsername: process.env.APP_AUTH_DEFAULT_USERNAME ?? 'admin',
  defaultPassword: process.env.APP_AUTH_DEFAULT_PASSWORD ?? 'admin123',
  minioEndpoint: process.env.MINIO_ENDPOINT || 'http://localhost:9000',
  minioAccessKey: process.env.MINIO_ACCESS_KEY || 'minioadmin',
  minioSecretKey: process.env.MINIO_SECRET_KEY || 'minioadmin',
  minioBucket: process.env.MINIO_BUCKET_NAME || 'agent-flow',
  minioPublicUrl: process.env.MINIO_PUBLIC_URL || 'http://localhost:9000',
  skillsPath: process.env.SKILLS_PATH || path.join(repoDir, 'backend', 'src', 'main', 'resources', 'skills'),
  uvxPath: process.env.MCP_UVX_PATH || 'uvx',
};

const WEAK_SECRETS = new Set([
  'agentflow-one-jwt-secret-key-change-me-to-a-long-random-string',
  'agentflow-dev-jwt-secret-key-only-for-development',
  'secret',
  'password',
  '123456',
  'jwt-secret',
  'your-secret-key',
  'default-secret',
]);

export function jwtSecret(): string {
  if (config.jwtSecretConfigured && !WEAK_SECRETS.has(config.jwtSecretConfigured)) {
    return config.jwtSecretConfigured;
  }
  const isLocal = !process.env.NODE_ENV || process.env.NODE_ENV === 'development';
  if (isLocal) return crypto.randomBytes(48).toString('base64url');
  return config.jwtSecretConfigured || crypto.randomBytes(48).toString('base64url');
}

export function jwtAlgorithm(secret: string): 'HS256' | 'HS384' | 'HS512' {
  const length = Buffer.byteLength(secret, 'utf8');
  if (length >= 64) return 'HS512';
  if (length >= 48) return 'HS384';
  return 'HS256';
}

export const isSqlite = config.dbType === 'sqljs';
