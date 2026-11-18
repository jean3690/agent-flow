package com.agentflow.sdk;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

import static org.junit.jupiter.api.Assertions.*;

class AgentFlowClientTest {
    private HttpServer server;
    private AgentFlowClient client;

    @BeforeEach
    void setUp() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.start();
        client = new AgentFlowClient("http://127.0.0.1:" + server.getAddress().getPort(), "af_demo");
    }

    @AfterEach
    void tearDown() {
        server.stop(0);
    }

    @Test
    void sendsAuthAndUnwrapsRunResult() throws Exception {
        server.createContext("/api/workflows/5/run", exchange -> {
            assertEquals("af_demo", exchange.getRequestHeaders().getFirst("X-API-Key"));
            assertEquals("POST", exchange.getRequestMethod());
            respond(exchange, 200, "application/json", "{\"code\":0,\"data\":{\"status\":\"SUCCESS\"}}");
        });
        assertEquals("SUCCESS", client.runWorkflow(5, Map.of()).path("status").asText());
    }

    @Test
    void deliversEventsBeforeResponseEnds() throws Exception {
        CountDownLatch received = new CountDownLatch(1);
        AtomicBoolean receivedBeforeClose = new AtomicBoolean();
        server.createContext("/api/workflows/5/execute", exchange -> {
            try (exchange) {
                exchange.getResponseHeaders().set("Content-Type", "text/event-stream");
                exchange.sendResponseHeaders(200, 0);
                exchange.getResponseBody().write("event: run_started\ndata: {}\n\n".getBytes(StandardCharsets.UTF_8));
                exchange.getResponseBody().flush();
                try {
                    receivedBeforeClose.set(received.await(2, TimeUnit.SECONDS));
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }
        });
        client.executeWorkflowStream(5, Map.of(), event -> received.countDown());
        assertTrue(receivedBeforeClose.get(), "callback must run while the upstream response is still open");
    }

    @ParameterizedTest
    @ValueSource(strings = {"\n", "\r\n", "\r"})
    void handlesMultilineJsonAndDefaultEvent(String newline) throws Exception {
        String body = String.join(newline, "\ufeff: heartbeat", "", "data: {\"text\":", "data: \"你好\"}", "", "");
        server.createContext("/api/workflows/5/execute", exchange -> respond(exchange, 200, "text/event-stream", body));
        List<AgentFlowClient.Event> events = new ArrayList<>();
        client.executeWorkflowStream(5, Map.of(), events::add);
        assertEquals(1, events.size());
        assertEquals("message", events.get(0).name());
        assertEquals("你好", events.get(0).data().path("text").asText());
    }

    @ParameterizedTest
    @ValueSource(strings = {"", "\n", "\r\n"})
    void keepsFinalEventWithoutBlankLine(String suffix) throws Exception {
        String body = "event: run_finished\ndata: {\"status\":\"SUCCESS\"}" + suffix;
        server.createContext("/api/workflows/5/execute", exchange -> respond(exchange, 200, "text/event-stream", body));
        List<AgentFlowClient.Event> events = new ArrayList<>();
        client.executeWorkflowStream(5, Map.of(), events::add);
        assertEquals(1, events.size());
        assertEquals("run_finished", events.get(0).name());
    }

    @Test
    void surfacesStreamingHttpErrors() {
        server.createContext("/api/workflows/5/execute", exchange -> respond(exchange, 401, "application/json", "bad key"));
        ApiException error = assertThrows(ApiException.class,
                () -> client.executeWorkflowStream(5, Map.of(), event -> fail("must not emit an error response")));
        assertEquals(401, error.getCode());
        assertTrue(error.getMessage().contains("bad key"));
    }

    @Test
    void encodesWorkflowSearchKeyword() throws Exception {
        server.createContext("/api/workflows", exchange -> {
            assertEquals("page=1&size=10&keyword=%E4%B8%AD%E6%96%87+%26%3F", exchange.getRequestURI().getRawQuery());
            respond(exchange, 200, "application/json", "{\"code\":0,\"data\":[]}");
        });
        assertTrue(client.listWorkflows(1, 10, "中文 &?").isArray());
    }

    private void respond(HttpExchange exchange, int status, String contentType, String body) throws IOException {
        try (exchange) {
            byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", contentType);
            exchange.sendResponseHeaders(status, bytes.length);
            exchange.getResponseBody().write(bytes);
        }
    }
}
