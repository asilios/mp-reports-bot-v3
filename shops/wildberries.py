from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

WB_BASE = "https://statistics-api.wildberries.ru"
WB_CONTENT_BASE = "https://feedbacks-api.wildberries.ru"
WB_WAREHOUSE_BASE = "https://marketplace-api.wildberries.ru"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=60)


class WBClient:
    def __init__(self, shop_id: str, api_key: str, shop_name: str):
        self.shop_id = shop_id
        self.shop_name = shop_name
        self._headers = {
            "Authorization": api_key,
            "Content-Type": "application/json",
        }
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=DEFAULT_TIMEOUT)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get(self, base: str, endpoint: str, params: dict) -> Any | None:
        url = f"{base}{endpoint}"
        session = await self._get_session()
        for attempt in range(3):
            try:
                async with session.get(url, params=params, headers=self._headers) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error("[%s] %s returned %s: %s", self.shop_id, endpoint, resp.status, body[:800])
                        return None
                    return await resp.json()
            except Exception as exc:
                logger.warning("[%s] %s attempt %s failed: %s", self.shop_id, endpoint, attempt + 1, exc)
                if attempt == 2:
                    logger.exception("[%s] %s failed after retries", self.shop_id, endpoint)
                    return None
                await asyncio.sleep(1.5 * (attempt + 1))
        return None

    async def get_sales(self, date_from: date, date_to: date) -> list[dict[str, Any]]:
        # WB Statistics API — orders report
        data = await self._get(
            WB_BASE,
            "/api/v1/supplier/orders",
            {
                "dateFrom": date_from.isoformat(),
                "dateTo": date_to.isoformat(),
                "flag": 0,  # 0 = all orders, 1 = only new since dateFrom
            },
        )
        if not data:
            return []

        # Aggregate by nmId (product article)
        from collections import defaultdict
        agg: dict[str, dict] = defaultdict(lambda: {"sku_name": "", "units_sold": 0, "revenue": 0.0, "returns": 0})
        for order in data:
            nm_id = str(order.get("nmId") or order.get("nmid") or "unknown")
            name = order.get("subject") or order.get("supplierArticle") or nm_id
            price = float(order.get("totalPrice") or order.get("finishedPrice") or 0)
            is_return = order.get("isReturn", False)
            agg[nm_id]["sku_name"] = name
            if is_return:
                agg[nm_id]["returns"] += 1
            else:
                agg[nm_id]["units_sold"] += 1
                agg[nm_id]["revenue"] += price

        return [
            {
                "sku_id": sku_id,
                "sku_name": vals["sku_name"],
                "units_sold": vals["units_sold"],
                "revenue": vals["revenue"],
                "returns": vals["returns"],
            }
            for sku_id, vals in agg.items()
        ]

    async def get_stock_levels(self) -> list[dict[str, Any]]:
        data = await self._get(
            WB_BASE,
            "/api/v1/supplier/stocks",
            {"dateFrom": "2000-01-01"},  # WB requires a dateFrom but returns current stocks
        )
        if not data:
            return []

        from collections import defaultdict
        agg: dict[str, dict] = defaultdict(lambda: {"sku_name": "", "stock": 0})
        for item in data:
            nm_id = str(item.get("nmId") or "unknown")
            agg[nm_id]["sku_name"] = item.get("subject") or item.get("supplierArticle") or nm_id
            agg[nm_id]["stock"] += int(item.get("quantity") or 0)

        return [
            {"sku_id": sku_id, "sku_name": vals["sku_name"], "stock": vals["stock"]}
            for sku_id, vals in agg.items()
        ]

    async def get_reviews(self, limit: int = 50) -> list[dict[str, Any]]:
        data = await self._get(
            WB_CONTENT_BASE,
            "/api/v1/feedbacks",
            {
                "isAnswered": "false",
                "take": limit,
                "skip": 0,
                "order": "dateDesc",
            },
        )
        if not data:
            return []

        feedbacks = data.get("data", {}).get("feedbacks") or []
        return [
            {
                "review_id": str(fb.get("id", "")),
                "rating": int(fb.get("productValuation") or 0),
                "text": fb.get("text") or "",
                "sku_name": fb.get("productDetails", {}).get("productName") or "Unknown item",
                "created_at": fb.get("createdDate") or "",
            }
            for fb in feedbacks
        ]


def build_wb_clients(wb_shops: dict) -> dict[str, WBClient]:
    return {
        shop_id: WBClient(shop_id=shop_id, api_key=cfg["api_key"], shop_name=cfg["name"])
        for shop_id, cfg in wb_shops.items()
        if cfg.get("api_key")
    }
