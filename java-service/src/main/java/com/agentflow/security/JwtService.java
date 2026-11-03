package com.agentflow.security;

import com.agentflow.config.AgentFlowProperties;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date;

@Component
public class JwtService {

    private final SecretKey key;
    private final long expireMillis;

    public JwtService(AgentFlowProperties properties) {
        byte[] secret = properties.getJwt().getSecret().getBytes(StandardCharsets.UTF_8);
        this.key = Keys.hmacShaKeyFor(secret);
        this.expireMillis = properties.getJwt().getExpireHours() * 3600_000L;
    }

    public String issue(Long userId, String username, String role) {
        Date now = new Date();
        return Jwts.builder()
                .subject(String.valueOf(userId))
                .claim("username", username)
                .claim("role", role)
                .issuedAt(now)
                .expiration(new Date(now.getTime() + expireMillis))
                .signWith(key)
                .compact();
    }

    public CurrentUser parse(String token) {
        Claims claims = Jwts.parser()
                .verifyWith(key)
                .build()
                .parseSignedClaims(token)
                .getPayload();
        return new CurrentUser(
                Long.valueOf(claims.getSubject()),
                claims.get("username", String.class),
                claims.get("role", String.class));
    }
}
