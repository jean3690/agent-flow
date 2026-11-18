package com.agentflow.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.LinkedHashMap;
import java.util.Map;

@Data
@ConfigurationProperties(prefix = "agentflow")
public class AgentFlowProperties {

    private Jwt jwt = new Jwt();
    private Auth auth = new Auth();
    private Ai ai = new Ai();
    private Cors cors = new Cors();
    private Internal internal = new Internal();
    private Crypto crypto = new Crypto();
    private Pricing pricing = new Pricing();

    @Data
    public static class Jwt {
        private String secret = "agent-flow-local-secret-key-please-change";
        private int expireHours = 12;
    }

    @Data
    public static class Auth {
        private String defaultUsername = "admin";
        private String defaultPassword = "admin123";
    }

    @Data
    public static class Ai {
        private String baseUrl = "http://127.0.0.1:8000";
        private int timeoutMs = 120000;
        private int connectTimeoutMs = 5000;
    }

    @Data
    public static class Cors {
        private String allowedOrigins = "http://localhost:5173,http://127.0.0.1:5173";
    }

    @Data
    public static class Internal {
        private String token = "agent-flow-internal";
    }

    @Data
    public static class Crypto {
        private String key = "agent-flow-local-crypto-key";
    }

    /** 每 1K token 的估算单价（美元），用于执行成本统计；未知模型使用 default 费率。 */
    @Data
    public static class Pricing {
        private double defaultInputPer1k = 0;
        private double defaultOutputPer1k = 0;
        private Map<String, ModelPrice> models = new LinkedHashMap<>();
    }

    @Data
    public static class ModelPrice {
        private double inputPer1k = 0;
        private double outputPer1k = 0;
    }
}
