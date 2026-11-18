package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.entity.ApiKey;
import com.agentflow.entity.User;
import com.agentflow.mapper.ApiKeyMapper;
import com.agentflow.mapper.UserMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.crypto.password.PasswordEncoder;

import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ApiKeyServiceTest {

    @Mock
    private ApiKeyMapper apiKeyMapper;

    @Mock
    private UserMapper userMapper;

    @Mock
    private PasswordEncoder passwordEncoder;

    private ApiKeyService service;

    @BeforeEach
    void setUp() {
        service = new ApiKeyService(apiKeyMapper, userMapper, passwordEncoder);
    }

    @Test
    void rejectsExpiryInThePast() {
        when(userMapper.selectById(5L)).thenReturn(owner());

        assertThatThrownBy(() -> service.issue("svc", 5L, LocalDateTime.now().minusMinutes(1)))
                .isInstanceOf(BizException.class)
                .hasMessageContaining("过期时间");

        verify(apiKeyMapper, never()).insert(any(ApiKey.class));
    }

    @Test
    void storesExpiryAndReturnsRawKeyOnce() {
        when(userMapper.selectById(5L)).thenReturn(owner());
        when(passwordEncoder.encode(any())).thenReturn("bcrypt-hash");
        LocalDateTime expiry = LocalDateTime.now().plusDays(7);

        ApiKeyService.ApiKeyIssue issue = service.issue("svc", 5L, expiry);

        assertThat(issue.rawKey()).startsWith("af_");
        assertThat(issue.expiresAt()).isEqualTo(expiry);

        ArgumentCaptor<ApiKey> captor = ArgumentCaptor.forClass(ApiKey.class);
        verify(apiKeyMapper).insert(captor.capture());
        assertThat(captor.getValue().getExpiresAt()).isEqualTo(expiry);
        assertThat(captor.getValue().getKeyHash()).isEqualTo("bcrypt-hash");
        assertThat(captor.getValue().getKeyHash()).doesNotContain(issue.rawKey());
    }

    @Test
    void authenticateRejectsExpiredKey() {
        ApiKey key = new ApiKey();
        key.setEnabled(1);
        key.setKeyHash("bcrypt-hash");
        key.setOwnerUserId(5L);
        key.setExpiresAt(LocalDateTime.now().minusDays(1));
        when(apiKeyMapper.selectList(any())).thenReturn(List.of(key));
        when(passwordEncoder.matches("af_expired", "bcrypt-hash")).thenReturn(true);

        assertThat(service.authenticate("af_expired")).isEmpty();
    }

    @Test
    void authenticateReturnsOwnerForValidKey() {
        ApiKey key = new ApiKey();
        key.setEnabled(1);
        key.setKeyHash("bcrypt-hash");
        key.setOwnerUserId(5L);
        when(apiKeyMapper.selectList(any())).thenReturn(List.of(key));
        when(passwordEncoder.matches("af_valid", "bcrypt-hash")).thenReturn(true);
        when(userMapper.selectById(5L)).thenReturn(owner());

        assertThat(service.authenticate("af_valid"))
                .isPresent()
                .get()
                .satisfies(user -> {
                    assertThat(user.id()).isEqualTo(5L);
                    assertThat(user.role()).isEqualTo("ADMIN");
                });
    }

    private User owner() {
        User user = new User();
        user.setId(5L);
        user.setUsername("admin");
        user.setRole("ADMIN");
        return user;
    }
}
