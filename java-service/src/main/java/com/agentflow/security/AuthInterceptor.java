package com.agentflow.security;

import com.agentflow.common.ApiResponse;
import com.agentflow.service.ApiKeyService;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import java.nio.charset.StandardCharsets;
import java.util.Optional;

@Component
@RequiredArgsConstructor
public class AuthInterceptor implements HandlerInterceptor {

    private final JwtService jwtService;
    private final ObjectMapper objectMapper;
    private final ApiKeyService apiKeyService;

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) throws Exception {
        if ("OPTIONS".equalsIgnoreCase(request.getMethod())) {
            return true;
        }
        // 文件下载保持匿名（img/video/audio 标签无法携带 Authorization）；管理操作仍需鉴权。
        String path = request.getRequestURI().substring(request.getContextPath().length());
        if ("GET".equalsIgnoreCase(request.getMethod()) && path.startsWith("/api/files/")) {
            return true;
        }
        // Webhook 触发器凭 URL 中的随机令牌鉴权，调用方无需账号或 API Key。
        if ("POST".equalsIgnoreCase(request.getMethod()) && path.startsWith("/api/triggers/webhook/")) {
            return true;
        }
        // 机器凭证优先：X-API-Key
        String apiKey = request.getHeader("X-API-Key");
        if (apiKey != null && !apiKey.isBlank()) {
            Optional<CurrentUser> keyUser = apiKeyService.authenticate(apiKey);
            if (keyUser.isPresent()) {
                UserContext.set(keyUser.get());
                return true;
            }
            return reject(response, "API Key 无效或已过期");
        }
        // 回落到服务账号 JWT
        String header = request.getHeader("Authorization");
        if (header == null || !header.startsWith("Bearer ")) {
            return reject(response, "未登录或 token 缺失");
        }
        try {
            CurrentUser user = jwtService.parse(header.substring(7));
            UserContext.set(user);
            return true;
        } catch (Exception ex) {
            return reject(response, "token 无效或已过期");
        }
    }

    @Override
    public void afterCompletion(HttpServletRequest request, HttpServletResponse response, Object handler, Exception ex) {
        UserContext.clear();
    }

    private boolean reject(HttpServletResponse response, String message) throws Exception {
        response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.getWriter().write(objectMapper.writeValueAsString(ApiResponse.error(4010, message)));
        return false;
    }
}
