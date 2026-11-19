package com.agentflow.config;

import com.agentflow.service.RealtimeTranslationBridge;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;
import org.springframework.web.socket.server.standard.ServletServerContainerFactoryBean;

import java.util.Arrays;

@Configuration
@EnableWebSocket
@RequiredArgsConstructor
public class TranslationWebSocketConfig implements WebSocketConfigurer {
    private final RealtimeTranslationBridge bridge;
    private final AgentFlowProperties properties;

    @Override public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        String[] origins = Arrays.stream(properties.getCors().getAllowedOrigins().split(","))
                .map(String::trim).filter(value -> !value.isEmpty()).toArray(String[]::new);
        registry.addHandler(bridge, "/api/translations/realtime/ws").setAllowedOrigins(origins);
    }

    @Bean public ServletServerContainerFactoryBean translationWebSocketContainer() {
        ServletServerContainerFactoryBean container = new ServletServerContainerFactoryBean();
        container.setMaxTextMessageBufferSize(64 * 1024);
        container.setMaxSessionIdleTimeout(60_000L);
        return container;
    }
}
