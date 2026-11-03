package com.agentflow.security;

import com.agentflow.config.AgentFlowProperties;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class JwtServiceTest {

    private JwtService service() {
        AgentFlowProperties properties = new AgentFlowProperties();
        properties.getJwt().setSecret("agent-flow-test-secret-key-0123456789");
        properties.getJwt().setExpireHours(1);
        return new JwtService(properties);
    }

    @Test
    void issuesAndParsesToken() {
        JwtService jwtService = service();
        String token = jwtService.issue(7L, "admin", "ADMIN");
        CurrentUser user = jwtService.parse(token);
        assertThat(user.id()).isEqualTo(7L);
        assertThat(user.username()).isEqualTo("admin");
    }

    @Test
    void rejectsTamperedToken() {
        JwtService jwtService = service();
        String token = jwtService.issue(7L, "admin", "ADMIN");
        assertThatThrownBy(() -> jwtService.parse(token + "x")).isInstanceOf(Exception.class);
    }
}
