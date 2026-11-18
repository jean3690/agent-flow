package com.agentflow.service;

import com.agentflow.config.AgentFlowProperties;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ModelPricingServiceTest {

    @Test
    void estimatesKnownModel() {
        AgentFlowProperties properties = new AgentFlowProperties();
        AgentFlowProperties.ModelPrice price = new AgentFlowProperties.ModelPrice();
        price.setInputPer1k(0.00015);
        price.setOutputPer1k(0.0006);
        properties.getPricing().getModels().put("gpt-4o-mini", price);

        ModelPricingService service = new ModelPricingService(properties);

        assertThat(service.estimate("gpt-4o-mini", 1000, 500))
                .isEqualByComparingTo("0.00045");
        assertThat(service.estimate("openai/gpt-4o-mini", 1000, 0))
                .isEqualByComparingTo("0.00015");
    }

    @Test
    void unknownModelUsesDefaultRates() {
        AgentFlowProperties properties = new AgentFlowProperties();
        properties.getPricing().setDefaultInputPer1k(0.001);
        properties.getPricing().setDefaultOutputPer1k(0.002);

        ModelPricingService service = new ModelPricingService(properties);

        assertThat(service.estimate("unknown-model", 1000, 1000))
                .isEqualByComparingTo("0.003");
    }
}
