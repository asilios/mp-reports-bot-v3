from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

OZON_BASE = "https://api-seller.ozon.ru"
DEFAULT_TIMEOUT = aiohttp.ClientTimeout(total=60)


class OzonClient:
    def __init__(self, shop_id: str, client_id: str, api_key: str, shop_name: str):
        self.shop_id = shop_id
        self.shop_name = shop_name
        self._headers = {
            "Client-Id": client_id,
            "Api-Key": api_key,
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

    async def _post(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        url = f"{OZON_BASE}{endpoint}"
        session = await self._get_session()
        for attempt in range(3):
            try:
                async with session.post(url, json=payload, headers=self._headers) as resp:
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
        data = await self._post(
            "/v1/analytics/data",
            {
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "dimension": ["sku"],
                "metrics": ["ordered_units", "revenue", "returns"],
                "limit": 1000,
            },
        )
        if not data:
            return []

        results: list[dict[str, Any]] = []
        for row in data.get("result", {}).get("data", []):
            sku_id = None
            sku_name = None
            for dim in row.get("dimensions", []):
                raw_id = dim.get("id")
                dim_id = str(raw_id).lower() if raw_id is not None else ""
                dim_name = dim.get("name", "Unknown item")
                if dim_id.isdigit():
                    sku_id = dim_id
                    sku_name = sku_name or dim_name
                elif dim_id in {"sku", "sku_id", "offer_id", "product_id"}:
                    sku_id = dim_name
                    sku_name = sku_name or dim_name
                elif dim_id in {"sku_name", "name", "product_name"}:
                    sku_name = dim_name
                elif sku_id is None and sku_name is None:
                    sku_name = dim_name

            metrics = row.get("metrics") or []
            results.append(
                {
                    "sku_id": str(sku_id or sku_name or "unknown"),
                    "sku_name": sku_name or str(sku_id or "Unknown item"),
                    "units_sold": int(metrics[0]) if len(metrics) > 0 and metrics[0] is not None else 0,
                    "revenue": float(metrics[1]) if len(metrics) > 1 and metrics[1] is not None else 0.0,
                    "returns": int(metrics[2]) if len(metrics) > 2 and metrics[2] is not None else 0,
                }
            )
        return results

    async def get_stock_levels(self) -> list[dict[str, Any]]:
        data = await self._post(
            "/v3/product/info/stocks",
            {
                "filter": {"visibility": "ALL"},
                "limit": 1000,
            },
        )
        if not data:
            return []

        results: list[dict[str, Any]] = []
        for item in data.get("result", {}).get("items", []):
            total_stock = sum(stock_item.get("present", 0) for stock_item in item.get("stocks", []))
            results.append(
                {
                    "sku_id": str(item.get("product_id")),
                    "sku_name": item.get("name", "Unknown"),
                    "stock": int(total_stock),
                }
            )
        return results

    async def get_reviews(self, limit: int = 50) -> list[dict[str, Any]]:
        data = await self._post(
            "/v1/review/list",
            {
                "sort_dir": "DESC",
                "limit": limit,
            },
        )
        if not data:
            return []

        return [
            {
                "review_id": str(review.get("id")),
                "rating": int(review.get("rating", 0) or 0),
                "text": review.get("text", "") or "",
                "sku_name": review.get("product_name", "Unknown item"),
                "created_at": review.get("created_at", ""),
            }
            for review in data.get("reviews", [])
        ]


def build_ozon_clients(ozon_shops: dict) -> dict[str, OzonClient]:
    return {
        shop_id: OzonClient(
            shop_id=shop_id,
            client_id=cfg["client_id"],
            api_key=cfg["api_key"],
            shop_name=cfg["name"],
        )
        for shop_id, cfg in ozon_shops.items()
        if cfg.get("client_id") and cfg.get("api_key")
    }


async def close_clients(clients: dict[str, OzonClient]) -> None:
    for client in clients.values():
        await client.close()
