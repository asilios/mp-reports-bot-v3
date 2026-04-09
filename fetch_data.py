from __future__ import annotations

import asyncio
from datetime import date, timedelta

from config import OZON_SHOPS, validate_config
from db.database import executemany, init_db
from scheduler.jobs import UPSERT_SALES_SQL
from shops.ozon import build_ozon_clients, close_clients


async def fetch_historical_data(start_date: date, end_date: date) -> None:
    clients = build_ozon_clients(OZON_SHOPS)
    total = 0
    current_date = start_date
    try:
        while current_date <= end_date:
            for _, client in clients.items():
                sales = await client.get_sales(current_date, current_date)
                executemany(
                    UPSERT_SALES_SQL,
                    [
                        (
                            client.shop_id,
                            current_date,
                            item["sku_id"],
                            item["sku_name"],
                            int(item["units_sold"]),
                            float(item["revenue"]),
                            int(item["returns"]),
                        )
                        for item in sales
                    ],
                )
                print(f"✅ {client.shop_name} {current_date.isoformat()}: {len(sales)} items saved")
                total += len(sales)
            current_date += timedelta(days=1)
    finally:
        await close_clients(clients)

    print(f"Done! {total} records saved from {start_date} to {end_date}")


if __name__ == "__main__":
    validate_config()
    init_db()
    asyncio.run(fetch_historical_data(date(2026, 1, 1), date(2026, 4, 8)))
