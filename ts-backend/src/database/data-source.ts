import { DataSource } from 'typeorm';
import fs from 'fs';
import mysql from 'mysql2/promise';
import { SnakeNamingStrategy } from 'typeorm-naming-strategies';
import { config, isSqlite } from '../config';
import { ENTITIES, NodeDefinition } from './entities';

export const AppDataSource = new DataSource({
  type: config.dbType as any,
  ...(isSqlite
    ? {
        driver: require('sql.js'),
        location: process.env.AGENTFLOW_DATABASE_URL ? config.sqlitePath : undefined,
        autoSave: false,
      }
    : {
        host: config.mysqlHost,
        port: config.mysqlPort,
        username: config.mysqlUsername,
        password: config.mysqlPassword,
        database: config.mysqlDatabase,
        charset: 'utf8mb4',
      }),
  entities: ENTITIES,
  namingStrategy: new SnakeNamingStrategy(),
  synchronize: isSqlite && config.autoMigrate,
  logging: false,
} as any);

async function ensureMysqlDatabase(): Promise<void> {
  const connection = await mysql.createConnection({
    host: config.mysqlHost,
    port: config.mysqlPort,
    user: config.mysqlUsername,
    password: config.mysqlPassword,
  });
  try {
    await connection.query(
      `CREATE DATABASE IF NOT EXISTS \`${config.mysqlDatabase}\` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci`,
    );
  } finally {
    await connection.end();
  }
}

function schemaStatements(sql: string): string[] {
  return sql
    .split(';')
    .map((part) =>
      part
        .split('\n')
        .filter((line) => line.trim() && !line.trim().startsWith('--'))
        .join('\n')
        .trim(),
    )
    .filter((statement) => {
      const upper = statement.toUpperCase();
      return statement && !upper.startsWith('CREATE DATABASE') && !upper.startsWith('USE ');
    });
}

async function applySchema(): Promise<void> {
  if (!fs.existsSync(config.schemaSqlPath)) {
    console.warn(`[db] schema.sql not found at ${config.schemaSqlPath}`);
    return;
  }
  const connection = await mysql.createConnection({
    host: config.mysqlHost,
    port: config.mysqlPort,
    user: config.mysqlUsername,
    password: config.mysqlPassword,
    database: config.mysqlDatabase,
    charset: 'utf8mb4',
    multipleStatements: false,
  });
  try {
    for (const statement of schemaStatements(fs.readFileSync(config.schemaSqlPath, 'utf8'))) {
      await connection.query(statement);
    }
    console.log(`[db] Applied schema.sql to ${config.mysqlDatabase}`);
  } finally {
    await connection.end();
  }
}

async function tableExists(table: string): Promise<boolean> {
  const connection = await mysql.createConnection({
    host: config.mysqlHost,
    port: config.mysqlPort,
    user: config.mysqlUsername,
    password: config.mysqlPassword,
    database: config.mysqlDatabase,
  });
  try {
    const [rows] = await connection.query(
      'SELECT COUNT(*) AS count FROM information_schema.TABLES WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?',
      [config.mysqlDatabase, table],
    );
    return Number((rows as any[])[0].count) > 0;
  } finally {
    await connection.end();
  }
}

const SEED_NODES = [
  ['input', '输入', 'IO', '📥', '{"type":"object","properties":{}}', '{"type":"object","properties":{"input":{"type":"string"}}}', '{"type":"object","properties":{"defaultValue":{"type":"string"}}}'],
  ['output', '输出', 'IO', '📤', '{"type":"object","properties":{"input":{"type":"string"}}}', '{"type":"object","properties":{"output":{"type":"string"}}}', '{"type":"object","properties":{}}'],
  ['condition', '条件分支', 'CONTROL', '🔀', '{"type":"object","properties":{"input":{"type":"object"}}}', '{"type":"object","properties":{"__selectedBranch__":{"type":"string"}}}', '{"type":"object","properties":{"conditions":{"type":"array"}}}'],
];

async function seedNodes(): Promise<void> {
  const count = await AppDataSource.getRepository(NodeDefinition).count();
  if (count > 0) return;
  for (const [nodeType, displayName, category, icon, inputSchema, outputSchema, configSchema] of SEED_NODES) {
    const node = new NodeDefinition();
    Object.assign(node, { nodeType, displayName, category, icon, inputSchema, outputSchema, configSchema, deleted: 0 });
    await AppDataSource.getRepository(NodeDefinition).save(node);
  }
}

export async function bootstrapDatabase(): Promise<void> {
  if (!isSqlite) {
    await ensureMysqlDatabase();
    if (!(await tableExists('workflow'))) await applySchema();
  }
  await AppDataSource.initialize();
  if (config.autoMigrate) await seedNodes();
}
