from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.config import get_settings


class ModelPricingService:
    def __init__(self) -> None:
        self._pricing = get_settings().pricing

    def _price_for(self, model: str | None) -> tuple[float, float]:
        models = self._pricing
        if model and models:
            if model in models:
                price = models[model]
                return price.get("input", 0), price.get("output", 0)
            normalized = model.lower()
            matches = [name for name in models if name.lower() in normalized]
            if matches:
                longest = max(matches, key=len)
                price = models[longest]
                return price.get("input", 0), price.get("output", 0)
        return 0.0, 0.0

    def estimate(self, model: str | None, prompt_tokens: int, completion_tokens: int) -> Decimal:
        input_price, output_price = self._price_for(model)
        thousand = Decimal(1000)
        prompt_cost = (
            Decimal(str(input_price)) * Decimal(max(0, prompt_tokens)) / thousand
        ).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
        completion_cost = (
            Decimal(str(output_price)) * Decimal(max(0, completion_tokens)) / thousand
        ).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
        return (prompt_cost + completion_cost).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
