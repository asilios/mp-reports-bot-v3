from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class WBClient:
    def __init__(self, shop_id: str, api_key: str, shop_name: str):
        self.shop_id = shop_id
        self.api_key = api_key
        self.shop_name = shop_name

    async def get_sales(self, *_args, **_kwargs):
        logger.warning("[%s] Wildberries support is not implemented yet", self.shop_id)
        return []

    async def get_stock_levels(self):
        logger.warning("[%s] Wildberries support is not implemented yet", self.shop_id)
        return []

    async def get_reviews(self, limit: int = 50):
        logger.warning("[%s] Wildberries support is not implemented yet", self.shop_id)
        return []


def build_wb_clients(wb_shops: dict) -> dict[str, WBClient]:
    return {
        shop_id: WBClient(shop_id=shop_id, api_key=cfg["api_key"], shop_name=cfg["name"])
        for shop_id, cfg in wb_shops.items()
        if cfg.get("api_key")
    }
