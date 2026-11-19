package com.agentflow.controller;

import com.agentflow.security.CurrentUser;
import com.agentflow.security.UserContext;
import com.agentflow.service.AiClient;
import com.agentflow.service.LlmProviderService;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class TranslationControllerTest {
    private AiClient ai;
    private LlmProviderService providers;
    private MockMvc mvc;

    @BeforeEach void setup() throws Exception {
        ai = mock(AiClient.class);
        providers = mock(LlmProviderService.class);
        when(ai.postJson(anyString(), any())).thenReturn(new ObjectMapper().readTree("{\"data\":{\"ticket\":\"opaque\"}}"));
        mvc = MockMvcBuilders.standaloneSetup(new TranslationController(ai, providers)).build();
        UserContext.set(new CurrentUser(7L, "user", "USER"));
    }
    @AfterEach void cleanup() { UserContext.clear(); }

    @Test void onlyForwardsServerCredentialsAndAuthenticatedOwner() throws Exception {
        when(providers.credentials("qwen")).thenReturn(Map.of("apiKey", "server-secret", "baseUrl", "https://dashscope.aliyuncs.com/compatible-mode/v1"));
        mvc.perform(post("/api/translations/realtime/sessions").contentType(MediaType.APPLICATION_JSON)
                .content("{\"targetLang\":\"ja\",\"userId\":99,\"apiKey\":\"injected\"}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.data.ticket").value("opaque"));
        var payload = org.mockito.ArgumentCaptor.forClass(Object.class);
        verify(ai).postJson(eq("/v1/translations/realtime/sessions"), payload.capture());
        Map<?, ?> body = (Map<?, ?>) payload.getValue();
        assertThat(body.get("apiKey")).isEqualTo("server-secret");
        assertThat(body.get("userId")).isEqualTo(7L);
        assertThat(body.get("model")).isEqualTo("qwen3.8-livetranslate-flash-realtime");
    }

    @Test void mockDoesNotResolveVendorKey() throws Exception {
        mvc.perform(post("/api/translations/realtime/sessions").contentType(MediaType.APPLICATION_JSON)
                .content("{\"provider\":\"mock\"}")).andExpect(status().isOk());
        verifyNoInteractions(providers);
    }

    @Test void invalidProviderIsRejectedBeforeCallingAi() throws Exception {
        mvc.perform(post("/api/translations/realtime/sessions").contentType(MediaType.APPLICATION_JSON)
                .content("{\"provider\":\"openai\"}")).andExpect(status().isBadRequest());
        verify(ai, never()).postJson(anyString(), any());
    }
}
