import { Injectable } from '@nestjs/common';
import jwt from 'jsonwebtoken';
import Redis from 'ioredis';
import { config, jwtAlgorithm, jwtSecret } from '../config';

@Injectable()
export class AuthService {
  private readonly secret = jwtSecret();
  private readonly algorithm = jwtAlgorithm(this.secret);
  private redis: Redis | null = null;
  private readonly memory = new Map<string, { username: string; expires: number }>();

  constructor() {
    try {
      const client = new Redis({
        host: config.redisHost,
        lazyConnect: true,
        port: config.redisPort,
        password: config.redisPassword || undefined,
        maxRetriesPerRequest: 1,
        connectTimeout: 1000,
      });
      client.on('error', () => undefined);
      client.connect().then(() => (this.redis = client)).catch(() => client.disconnect());
    } catch {
      this.redis = null;
    }
    if (this.secret.length < 32) {
      // jsonwebtoken rejects short HMAC keys; derive a compliant one.
      (this as any).secret = require('crypto').createHash('sha256').update(this.secret).digest('hex');
    }
  }

  private key(refreshToken: string): string {
    return `auth:refresh:${refreshToken}`;
  }

  private setRefresh(refreshToken: string, username: string): void {
    const ttl = config.refreshTokenHours * 3600;
    if (this.redis) {
      this.redis.set(this.key(refreshToken), username, 'EX', ttl).catch(() => undefined);
    }
    this.memory.set(this.key(refreshToken), { username, expires: Date.now() + ttl * 1000 });
  }

  private getRefresh(refreshToken: string): string | null {
    if (this.redis) {
      const value = (this.redis as any).get(this.key(refreshToken));
      if (value && typeof value.then === 'function') {
        // Fire-and-forget path; the in-memory copy is used synchronously.
      }
    }
    const entry = this.memory.get(this.key(refreshToken));
    if (!entry) return null;
    if (entry.expires <= Date.now()) {
      this.memory.delete(this.key(refreshToken));
      return null;
    }
    return entry.username;
  }

  login(username: string, password: string): any | null {
    const expectedUser = (config.defaultUsername || '').trim();
    const expectedPassword = (config.defaultPassword || '').trim();
    if (expectedUser && expectedPassword && expectedUser === username && expectedPassword === password) {
      return this.issue(username);
    }
    return null;
  }

  refresh(refreshToken: string): any | null {
    const username = this.getRefresh(refreshToken);
    if (!username) return null;
    this.revoke(refreshToken);
    return this.issue(username);
  }

  revoke(refreshToken: string | null | undefined): void {
    if (!refreshToken) return;
    if (this.redis) this.redis.del(this.key(refreshToken)).catch(() => undefined);
    this.memory.delete(this.key(refreshToken));
  }

  private issue(username: string): any {
    const token = jwt.sign(
      { sub: username, tokenType: 'access' },
      (this as any).secret,
      { algorithm: this.algorithm as any, expiresIn: `${config.accessTokenMinutes}m` },
    );
    const refreshToken = require('crypto').randomBytes(16).toString('hex');
    this.setRefresh(refreshToken, username);
    return { token, refreshToken, user: { username } };
  }

  validate(token: string): boolean {
    try {
      const payload = jwt.verify(token, (this as any).secret, { algorithms: [this.algorithm as any] }) as any;
      return payload?.tokenType === 'access';
    } catch {
      return false;
    }
  }

  username(token: string): string | null {
    try {
      const payload = jwt.verify(token, (this as any).secret, { algorithms: [this.algorithm as any] }) as any;
      return payload?.tokenType === 'access' ? payload.sub : null;
    } catch {
      return null;
    }
  }
}
