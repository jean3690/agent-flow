import { Body, Controller, Get, Headers, Post, Res } from '@nestjs/common';
import { AuthService } from './auth.service';
import { err, ok, text } from '../common';

@Controller('api/auth')
export class AuthController {
  constructor(private readonly auth: AuthService) {}

  @Post('login')
  login(@Body() body: any) {
    const username = text(body?.username);
    const password = text(body?.password);
    if (!username || !password) return err('用户名或密码错误');
    const tokens = this.auth.login(username, password);
    return tokens ? ok(tokens) : err('用户名或密码错误');
  }

  @Post('logout')
  logout(@Body() body: any) {
    this.auth.revoke(text(body?.refreshToken));
    return ok();
  }

  @Post('refresh')
  refresh(@Body() body: any) {
    const refreshToken = text(body?.refreshToken);
    if (!refreshToken) return err('Refresh Token 不能为空', 401);
    const tokens = this.auth.refresh(refreshToken);
    return tokens ? ok(tokens) : err('Refresh Token 无效或已过期', 401);
  }

  @Get('current')
  current(@Headers('authorization') authorization: string) {
    const username = authorization?.startsWith('Bearer ')
      ? this.auth.username(authorization.slice(7))
      : null;
    return username ? ok({ username }) : err('未认证', 401);
  }
}
