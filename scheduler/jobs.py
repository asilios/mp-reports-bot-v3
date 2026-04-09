from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from alerts.checks import check_bad_reviews, check_low_stock
from config import (
    DAILY_REPORT_HOUR,
    DAILY_REPORT_MINUTE,
    GROUP_CHAT_ID,
    OZON_SHOPS,
    REVIEW_CHECK_HOURS,
    STOCK_CHECK_HOURS,
    TIMEZONE,
    WB_SHOPS,
)
from db.database import executemany
from reports.builder import build_shop_report, build_united_report, resolve_period_range
from shops.ozon import build_ozon_clients, close_clients
from shops.wildberries import build_wb_clients
from utils.time_utils import yesterday_local

logger = logging.getLogger(__name__)

UPSERT_SALES_SQL = """
INSERT INTO sales_history (shop_id, sale_date, sku_id, sku_name, units_sold, revenue, returns)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (shop_id, sale_date, sku_id)
DO UPDATE SET
    sku_name = EXCLUDED.sku_name,
    units_sold = EXCLUDED.units_sold,
    revenue = EXCLUDED.revenue,
    returns = EXCLUDED.returns,
    updated_at = NOW()
"""


async def save_sales_for_day(clients: dict, sales_date) -> None:
    try:
        for shop_id, client in clients.items():
            sales = await client.get_sales(sales_date, sales_date)
            payload = [
                (
                    shop_id,
                    sales_date,
                    item["sku_id"],
                    item["sku_name"],
                    int(item["units_sold"]),
                    float(item["revenue"]),
                    int(item["returns"]),
                )
                for item in sales
            ]
            executemany(UPSERT_SALES_SQL, payload)
            logger.info("[%s] Saved %s sales records for %s", shop_id, len(sales), sales_date)
    finally:
        await close_clients({sid: client for sid, client in clients.items() if hasattr(client, 'close')})


async def send_daily_reports(bot) -> None:
    all_clients = {**build_ozon_clients(OZON_SHOPS), **build_wb_clients(WB_SHOPS)}
    shop_names = {sid: cfg["name"] for sid, cfg in {**OZON_SHOPS, **WB_SHOPS}.items()}
    sales_date = yesterday_local()
    await save_sales_for_day(all_clients, sales_date)

    period = resolve_period_range("yesterday")
    for shop_id, client in all_clients.items():
        msg = build_shop_report(shop_id, client.shop_name, period)
        await bot.send_message(chat_id=GROUP_CHAT_ID, text=msg, parse_mode="HTML")

    united_msg = build_united_report(shop_names, period)
    await bot.send_message(chat_id=GROUP_CHAT_ID, text=united_msg, parse_mode="HTML")
    logger.info("Daily reports sent")


async def run_stock_check(bot) -> None:
    all_clients = {**build_ozon_clients(OZON_SHOPS), **build_wb_clients(WB_SHOPS)}
    try:
        await check_low_stock(all_clients, bot, GROUP_CHAT_ID)
    finally:
        await close_clients({sid: client for sid, client in all_clients.items() if hasattr(client, 'close')})


async def run_review_check(bot) -> None:
    all_clients = {**build_ozon_clients(OZON_SHOPS), **build_wb_clients(WB_SHOPS)}
    try:
        await check_bad_reviews(all_clients, bot, GROUP_CHAT_ID)
    finally:
        await close_clients({sid: client for sid, client in all_clients.items() if hasattr(client, 'close')})


def setup_scheduler(app) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=TIMEZONE)
    bot = app.bot

    scheduler.add_job(
    lambda: app.create_task(send_daily_reports(bot)),
    IntervalTrigger(minutes=1, timezone=TIMEZONE),
    id="daily_reports",
    replace_existing=True,
    )
    scheduler.add_job(
        lambda: app.create_task(run_stock_check(bot)),
        IntervalTrigger(hours=STOCK_CHECK_HOURS, timezone=TIMEZONE),
        id="stock_check",
        replace_existing=True,
    )
    scheduler.add_job(
        lambda: app.create_task(run_review_check(bot)),
        IntervalTrigger(hours=REVIEW_CHECK_HOURS, timezone=TIMEZONE),
        id="review_check",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started")
    return scheduler
