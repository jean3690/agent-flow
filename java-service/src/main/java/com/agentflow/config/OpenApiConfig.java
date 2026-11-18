package com.agentflow.config;

import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class OpenApiConfig {

    @Bean
    public OpenAPI agentFlowOpenAPI() {
        return new OpenAPI().info(new Info()
                .title("Agent Flow API")
                .description("工作流编排与执行服务。提供工作流 CRUD、知识库检索、技能管理、以及工作流的同步/流式执行。"
                        + "可被外部程序直接调用：鉴权支持 API Key（请求头 X-API-Key）或服务账号 JWT（Authorization: Bearer）。"
                        + "所有接口统一返回 { code: 0 表示成功, message, data }。")
                .version("1.0.0"));
    }
}
