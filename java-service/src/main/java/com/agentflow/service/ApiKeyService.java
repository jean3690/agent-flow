package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.entity.ApiKey;
import com.agentflow.entity.User;
import com.agentflow.mapper.ApiKeyMapper;
import com.agentflow.mapper.UserMapper;
import com.agentflow.security.CurrentUser;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import lombok.RequiredArgsConstructor;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.Base64;
import java.util.List;
import java.util.Optional;

/**
 * API Key 机器凭证：明文仅在创建时返回一次，库中只存 BCrypt 哈希。
 * 鉴权时对所有启用中的 key 做 matches 校验（数量通常很少），并校验过期时间。
 */
@Service
@RequiredArgsConstructor
public class ApiKeyService {

    private static final String PREFIX = "af_";
    private static final int RAW_BYTES = 32;

    private final ApiKeyMapper apiKeyMapper;
    private final UserMapper userMapper;
    private final PasswordEncoder passwordEncoder;
    private final SecureRandom secureRandom = new SecureRandom();

    @Transactional
    public ApiKeyIssue issue(String name, Long ownerUserId, LocalDateTime expiresAt) {
        User owner = userMapper.selectById(ownerUserId);
        if (owner == null) {
            throw BizException.notFound("拥有者用户不存在: " + ownerUserId);
        }
        if (expiresAt != null && !expiresAt.isAfter(LocalDateTime.now())) {
            throw new BizException("过期时间必须晚于当前时间");
        }
        String raw = generateRawKey();
        ApiKey key = new ApiKey();
        key.setName(name);
        key.setKeyHash(passwordEncoder.encode(raw));
        key.setOwnerUserId(owner.getId());
        key.setEnabled(1);
        key.setExpiresAt(expiresAt);
        apiKeyMapper.insert(key);
        return new ApiKeyIssue(key.getId(), name, raw, mask(raw), owner.getUsername(), expiresAt);
    }

    public List<ApiKeyInfo> list() {
        return apiKeyMapper.selectList(null).stream().map(k -> new ApiKeyInfo(
                k.getId(),
                k.getName(),
                PREFIX + "****",
                k.getOwnerUserId(),
                k.getEnabled(),
                k.getExpiresAt(),
                k.getCreatedAt())).toList();
    }

    @Transactional
    public void revoke(Long id) {
        ApiKey existing = apiKeyMapper.selectById(id);
        if (existing == null) {
            throw BizException.notFound("API Key 不存在: " + id);
        }
        apiKeyMapper.deleteById(id);
    }

    public Optional<CurrentUser> authenticate(String rawKey) {
        if (rawKey == null || rawKey.isBlank()) {
            return Optional.empty();
        }
        List<ApiKey> candidates = apiKeyMapper.selectList(
                new LambdaQueryWrapper<ApiKey>().eq(ApiKey::getEnabled, 1));
        for (ApiKey k : candidates) {
            if (passwordEncoder.matches(rawKey, k.getKeyHash())) {
                if (k.getExpiresAt() != null && k.getExpiresAt().isBefore(LocalDateTime.now())) {
                    return Optional.empty();
                }
                User owner = userMapper.selectById(k.getOwnerUserId());
                if (owner == null) {
                    return Optional.empty();
                }
                return Optional.of(new CurrentUser(owner.getId(), "apikey:" + k.getName(), owner.getRole()));
            }
        }
        return Optional.empty();
    }

    private String generateRawKey() {
        byte[] bytes = new byte[RAW_BYTES];
        secureRandom.nextBytes(bytes);
        return PREFIX + Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private String mask(String raw) {
        if (raw == null || raw.length() < 12) {
            return "****";
        }
        return raw.substring(0, 6) + "****" + raw.substring(raw.length() - 4);
    }

    public record ApiKeyIssue(Long id, String name, String rawKey, String maskedKey,
                              String ownerUsername, LocalDateTime expiresAt) {
    }

    public record ApiKeyInfo(Long id, String name, String maskedKey, Long ownerUserId,
                             Integer enabled, LocalDateTime expiresAt, LocalDateTime createdAt) {
    }
}
