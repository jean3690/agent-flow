package com.agentflow.service;

import com.agentflow.config.AgentFlowProperties;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.Comparator;
import java.util.Map;

/** 按 token 用量估算执行成本；费率可在 application.yml 的 agentflow.pricing 覆盖。 */
@Service
@RequiredArgsConstructor
public class ModelPricingService {

    private static final BigDecimal THOUSAND = BigDecimal.valueOf(1000);

    private final AgentFlowProperties properties;

    public BigDecimal estimate(String model, int promptTokens, int completionTokens) {
        AgentFlowProperties.ModelPrice price = priceFor(model);
        BigDecimal promptCost = BigDecimal.valueOf(price.getInputPer1k())
                .multiply(BigDecimal.valueOf(Math.max(0, promptTokens)))
                .divide(THOUSAND, 8, RoundingMode.HALF_UP);
        BigDecimal completionCost = BigDecimal.valueOf(price.getOutputPer1k())
                .multiply(BigDecimal.valueOf(Math.max(0, completionTokens)))
                .divide(THOUSAND, 8, RoundingMode.HALF_UP);
        return promptCost.add(completionCost).setScale(6, RoundingMode.HALF_UP);
    }

    private AgentFlowProperties.ModelPrice priceFor(String model) {
        AgentFlowProperties.Pricing pricing = properties.getPricing();
        Map<String, AgentFlowProperties.ModelPrice> models = pricing.getModels();
        if (model != null && !model.isBlank() && models != null) {
            AgentFlowProperties.ModelPrice exact = models.get(model);
            if (exact != null) {
                return exact;
            }
            String normalized = model.toLowerCase();
            return models.entrySet().stream()
                    .filter(entry -> normalized.contains(entry.getKey().toLowerCase()))
                    .max(Comparator.comparingInt(entry -> entry.getKey().length()))
                    .map(Map.Entry::getValue)
                    .orElseGet(() -> defaultPrice(pricing));
        }
        return defaultPrice(pricing);
    }

    private AgentFlowProperties.ModelPrice defaultPrice(AgentFlowProperties.Pricing pricing) {
        AgentFlowProperties.ModelPrice price = new AgentFlowProperties.ModelPrice();
        price.setInputPer1k(pricing.getDefaultInputPer1k());
        price.setOutputPer1k(pricing.getDefaultOutputPer1k());
        return price;
    }
}
