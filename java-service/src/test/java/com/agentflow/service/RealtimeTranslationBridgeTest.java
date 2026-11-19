package com.agentflow.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;

import java.net.http.WebSocket;
import java.util.concurrent.CompletableFuture;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class RealtimeTranslationBridgeTest {
    private AiClient ai;
    private WebSocketSession browser;
    private WebSocket upstream;
    private RealtimeTranslationBridge bridge;
    private WebSocket.Listener listener;

    @BeforeEach void setup() throws Exception {
        ai = mock(AiClient.class);
        browser = mock(WebSocketSession.class);
        upstream = mock(WebSocket.class);
        when(browser.getId()).thenReturn("test");
        when(browser.isOpen()).thenReturn(true);
        when(upstream.sendText(anyString(), eq(true))).thenReturn(CompletableFuture.completedFuture(upstream));
        when(ai.openRealtime(any())).thenAnswer(call -> {
            listener = call.getArgument(0);
            return CompletableFuture.completedFuture(upstream);
        });
        bridge = new RealtimeTranslationBridge(ai, new ObjectMapper());
        bridge.afterConnectionEstablished(browser);
    }

    private void connect() throws Exception {
        bridge.handleMessage(browser, new TextMessage("{\"type\":\"connect\",\"ticket\":\"" + "a".repeat(43) + "\"}"));
    }

    @Test void relaysInitialTicketAndAudioWithoutPuttingTicketInUrl() throws Exception {
        connect();
        bridge.handleMessage(browser, new TextMessage("{\"type\":\"audio\",\"audio\":\"AAA=\"}"));
        verify(ai).openRealtime(any());
        verify(upstream).sendText(contains("ticket"), eq(true));
        verify(upstream).sendText(contains("audio"), eq(true));
        bridge.afterConnectionClosed(browser, CloseStatus.NORMAL);
        verify(upstream).abort();
    }

    @Test void reassemblesFragmentedEvents() throws Exception {
        connect();
        listener.onText(upstream, "{\"type\":", false);
        listener.onText(upstream, "\"session.ready\"}", true);
        var messages = org.mockito.ArgumentCaptor.forClass(org.springframework.web.socket.WebSocketMessage.class);
        verify(browser).sendMessage(messages.capture());
        assertThat(messages.getValue().getPayload()).isEqualTo("{\"type\":\"session.ready\"}");
        verify(upstream, times(2)).request(1);
    }

    @Test void rejectsMissingTicketWithoutOpeningUpstream() throws Exception {
        bridge.handleMessage(browser, new TextMessage("{\"type\":\"audio\"}"));
        verifyNoInteractions(ai);
        verify(browser).close(CloseStatus.POLICY_VIOLATION);
    }

    @Test void upstreamFailureDoesNotLeakItsException() throws Exception {
        connect();
        listener.onError(upstream, new RuntimeException("sk-secret must not appear"));
        var messages = org.mockito.ArgumentCaptor.forClass(org.springframework.web.socket.WebSocketMessage.class);
        verify(browser).sendMessage(messages.capture());
        assertThat(messages.getValue().getPayload().toString()).doesNotContain("sk-secret");
        verify(upstream).abort();
    }
}
