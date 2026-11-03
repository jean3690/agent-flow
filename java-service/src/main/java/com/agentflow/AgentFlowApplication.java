package com.agentflow;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;
import org.springframework.scheduling.annotation.EnableAsync;

@SpringBootApplication
@ConfigurationPropertiesScan
@MapperScan("com.agentflow.mapper")
@EnableAsync
public class AgentFlowApplication {

    public static void main(String[] args) {
        SpringApplication.run(AgentFlowApplication.class, args);
    }
}
