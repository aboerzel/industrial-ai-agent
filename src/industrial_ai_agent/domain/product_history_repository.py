from typing import Protocol

from industrial_ai_agent.domain.product_history import ProductHistory, ProductId


class ProductHistoryRepository(Protocol):
    def get_product_history(self, product_id: ProductId) -> ProductHistory | None: ...
