package com.agentflow.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.ConcurrentWebSocketSessionDecorator;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import java.net.http.WebSocket;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;

/** Transport only. Python validates the ticket and handles the vendor protocol. */
@Component
@RequiredArgsConstructor
public class RealtimeTranslationBridge extends TextWebSocketHandler {
    private final AiClient aiClient;
    private final ObjectMapper mapper;
    private final Map<String, Connection> connections = new ConcurrentHashMap<>();

    private static class Connection {
        final WebSocketSession browser;
        volatile CompletableFuture<WebSocket> upstream;
        Connection(WebSocketSession browser) {
            this.browser = new ConcurrentWebSocketSessionDecorator(browser, 5000, 2 * 1024 * 1024);
        }
    }

    @Override
    public void afterConnectionEstablished(WebSocketSession session) {
        session.setTextMessageSizeLimit(64 * 1024);
        Connection connection = new Connection(session);
        connections.put(session.getId(), connection);
        CompletableFuture.delayedExecutor(10, TimeUnit.SECONDS).execute(() -> {
            if (connection.upstream == null) fail(connection);
        });
    }

    @Override
    protected void handleTextMessage(WebSocketSession session, TextMessage message) throws Exception {
        Connection connection = connections.get(session.getId());
        if (connection == null) return;
        try {
            if (connection.upstream == null) {
                JsonNode hello = mapper.readTree(message.getPayload());
                if (!"connect".equals(hello.path("type").asText())
                        || !hello.path("ticket").asText().matches("[A-Za-z0-9_-]{43}")) {
                    fail(connection);
                    return;
                }
                // Ticket travels in the first frame, never in URLs or access logs.
                connection.upstream = aiClient.openRealtime(listener(connection));
                connection.upstream.thenCompose(ws -> ws.sendText(message.getPayload(), true))
                        .exceptionally(error -> { fail(connection); return null; });
            } else {
                connection.upstream.get(10, TimeUnit.SECONDS)
                        .sendText(message.getPayload(), true).get(5, TimeUnit.SECONDS);
            }
        } catch (Exception ex) {
            fail(connection);
        }
    }

    private WebSocket.Listener listener(Connection connection) {
        return new WebSocket.Listener() {
            private final StringBuilder buffer = new StringBuilder();
            @Override public void onOpen(WebSocket socket) { socket.request(1); }
            @Override public CompletionStage<?> onText(WebSocket socket, CharSequence data, boolean last) {
                buffer.append(data);
                if (buffer.length() > 2 * 1024 * 1024) {
                    fail(connection);
                    socket.abort();
                    return null;
                }
                if (last) {
                    try {
                        if (connection.browser.isOpen()) connection.browser.sendMessage(new TextMessage(buffer.toString()));
                    } catch (Exception ex) { fail(connection); }
                    buffer.setLength(0);
                }
                socket.request(1);
                return null;
            }
            @Override public CompletionStage<?> onClose(WebSocket socket, int code, String reason) {
                if (code == 1000) close(connection, CloseStatus.NORMAL);
                else fail(connection);
                return null;
            }
            @Override public void onError(WebSocket socket, Throwable error) { fail(connection); }
        };
    }

    private void fail(Connection connection) {
        try {
            if (connection.browser.isOpen()) connection.browser.sendMessage(new TextMessage(
                    "{\"type\":\"error\",\"message\":\"实时翻译连接失败，请重新开始或检查服务状态\"}"));
        } catch (Exception ignored) { }
        close(connection, CloseStatus.POLICY_VIOLATION);
    }

    private void close(Connection connection, CloseStatus status) {
        connections.remove(connection.browser.getId(), connection);
        if (connection.upstream != null) connection.upstream.thenAccept(WebSocket::abort);
        try { connection.browser.close(status); } catch (Exception ignored) { }
    }

    @Override public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
        Connection connection = connections.remove(session.getId());
        if (connection != null) close(connection, status);
    }

    @Override public void handleTransportError(WebSocketSession session, Throwable error) {
        Connection connection = connections.get(session.getId());
        if (connection != null) fail(connection);
    }
}
