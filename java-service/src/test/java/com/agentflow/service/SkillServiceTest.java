package com.agentflow.service;

import com.agentflow.common.BizException;
import com.agentflow.security.CurrentUser;
import com.agentflow.security.UserContext;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpStatus;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class SkillServiceTest {
    private final AiClient ai = mock(AiClient.class);
    private final SkillService service = new SkillService(ai);
    @AfterEach void cleanup() { UserContext.clear(); }
    @Test void onlyAdminCanMutateSharedSkills() {
        UserContext.set(new CurrentUser(1L, "user", "USER"));
        assertThatThrownBy(() -> service.save("test", "content")).isInstanceOfSatisfying(BizException.class, ex -> assertThat(ex.getStatus()).isEqualTo(HttpStatus.FORBIDDEN));
        assertThatThrownBy(() -> service.delete("test")).isInstanceOf(BizException.class);
        assertThatThrownBy(service::reload).isInstanceOf(BizException.class);
        verifyNoInteractions(ai);
    }
    @Test void blocksTraversalBeforeProxyingRequests() {
        assertThatThrownBy(() -> service.detail("../secret")).isInstanceOf(BizException.class);
        assertThatThrownBy(() -> service.reference("test", "../../secret.md")).isInstanceOf(BizException.class);
        verifyNoInteractions(ai);
    }
}
