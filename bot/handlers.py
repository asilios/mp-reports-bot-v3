from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from config import ADMIN_USER_IDS, ALL_SHOPS, OZON_SHOPS, WB_SHOPS
from db.database import executemany
from reports.builder import build_shop_report, build_united_report, resolve_period_range
from scheduler.jobs import UPSERT_SALES_SQL
from shops.ozon import build_ozon_clients, close_clients
from utils.time_utils import parse_date, today_local, yesterday_local

logger = logging.getLogger(__name__)


def is_admin(update: Update) -> bool:
    if not ADMIN_USER_IDS:
        return True
    user = update.effective_user
    return bool(user and user.id in ADMIN_USER_IDS)


async def cmd_start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 <b>Marketplace Report Bot</b>\n\n"
        "/report — generate a report on demand\n"
        "/status — check configured shops\n"
        "/fetch [from] [to] — backfill Ozon sales (admin only)\n\n"
        "/fetch_wb [from] [to] — backfill WB sales (admin only)\n\n"
        "Daily reports are sent automatically.",
        parse_mode="HTML",
    )


async def cmd_status(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    clients = build_ozon_clients(OZON_SHOPS)
    try:
        lines = ["🔍 <b>Shop status check</b>", ""]
        for _, client in clients.items():
            stock = await client.get_stock_levels()
            status = "✅ OK" if stock is not None else "❌ Unreachable"
            lines.append(f"{status} — {client.shop_name}")
        for _, cfg in WB_SHOPS.items():
            lines.append(f"⏳ WB stub only — {cfg['name']}")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
    finally:
        await close_clients(clients)


async def cmd_report(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard: list[list[InlineKeyboardButton]] = []
    if OZON_SHOPS:
        keyboard.append([InlineKeyboardButton("🛒 Ozon", callback_data="platform:ozon")])
    if WB_SHOPS:
        keyboard.append([InlineKeyboardButton("🟣 Wildberries", callback_data="platform:wb")])
    if len(ALL_SHOPS) > 1:
        keyboard.append([InlineKeyboardButton("📊 United report", callback_data="platform:united")])
    await update.message.reply_text("Choose a platform:", reply_markup=InlineKeyboardMarkup(keyboard))


async def handle_callback(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data or ""

    if data.startswith("platform:"):
        platform = data.split(":", 1)[1]
        if platform == "united":
            await _send_period_keyboard(query, "united:all")
            return
        shops = OZON_SHOPS if platform == "ozon" else WB_SHOPS
        keyboard = [[InlineKeyboardButton(cfg["name"], callback_data=f"shop:{shop_id}")] for shop_id, cfg in shops.items()]
        keyboard.append([InlineKeyboardButton("Both shops", callback_data=f"shop:both_{platform}")])
        await query.edit_message_text("Choose a shop:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data.startswith("shop:"):
        await _send_period_keyboard(query, data.split(":", 1)[1])
        return

    if data.startswith("period:"):
        parts = data.split(":")
        period_key = parts[-1]
        shop_key = ":".join(parts[1:-1])
        period = resolve_period_range(period_key)
        await query.edit_message_text("⏳ Generating report...")
        try:
            await _deliver_report(query, shop_key, period)
        except Exception:
            logger.exception("Report generation failed")
            await query.edit_message_text("❌ Failed to generate report. Please try again later.")


async def _send_period_keyboard(query, shop_key: str) -> None:
    keyboard = [
        [InlineKeyboardButton("Today", callback_data=f"period:{shop_key}:today")],
        [InlineKeyboardButton("Yesterday", callback_data=f"period:{shop_key}:yesterday")],
        [InlineKeyboardButton("This week", callback_data=f"period:{shop_key}:week")],
        [InlineKeyboardButton("This month", callback_data=f"period:{shop_key}:month")],
    ]
    await query.edit_message_text("Choose a period:", reply_markup=InlineKeyboardMarkup(keyboard))


async def _deliver_report(query, shop_key: str, period) -> None:
    shop_names = {sid: cfg["name"] for sid, cfg in ALL_SHOPS.items()}
    bot = query.get_bot()
    chat_id = query.message.chat_id

    if shop_key == "united:all":
        msg = await asyncio.to_thread(build_united_report, shop_names, period)
        await bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
        return

    if shop_key.startswith("both_"):
        platform = shop_key.split("_", 1)[1]
        shops = OZON_SHOPS if platform == "ozon" else WB_SHOPS
        for shop_id, cfg in shops.items():
            msg = await asyncio.to_thread(build_shop_report, shop_id, cfg["name"], period)
            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
        return

    cfg = ALL_SHOPS.get(shop_key)
    if not cfg:
        await bot.send_message(chat_id=chat_id, text="Shop not found.")
        return
    msg = await asyncio.to_thread(build_shop_report, shop_key, cfg["name"], period)
    await bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")


def _parse_fetch_args(text: str) -> tuple:
    parts = text.strip().split()
    if len(parts) == 1:
        y = yesterday_local()
        return y, y
    if len(parts) == 2:
        return parse_date(parts[1]), yesterday_local()
    if len(parts) == 3:
        return parse_date(parts[1]), parse_date(parts[2])
    raise ValueError("Usage: /fetch [YYYY-MM-DD] [YYYY-MM-DD]")


async def cmd_fetch(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.message.reply_text("❌ This command is admin-only.")
        return

    try:
        from_date, to_date = _parse_fetch_args(update.message.text or "")
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    latest_date = yesterday_local()
    if to_date > latest_date:
        await update.message.reply_text(f"❌ You can only fetch data through {latest_date.isoformat()}.")
        return
    if from_date > to_date:
        await update.message.reply_text("❌ Start date must be on or before the end date.")
        return

    await update.message.reply_text(
        f"⏳ Fetching Ozon sales data from {from_date.isoformat()} to {to_date.isoformat()}..."
    )

    clients = build_ozon_clients(OZON_SHOPS)
    total = 0
    current_date = from_date
    try:
        while current_date <= to_date:
            for _, client in clients.items():
                try:
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
                    total += len(sales)
                    await update.message.reply_text(
                        f"✅ {client.shop_name} {current_date.isoformat()}: {len(sales)} items saved"
                    )
                except Exception as exc:
                    logger.exception("Fetch failed for %s on %s", client.shop_id, current_date)
                    await update.message.reply_text(
                        f"❌ {client.shop_name} {current_date.isoformat()} failed: {exc}"
                    )
            current_date += timedelta(days=1)
    finally:
        await close_clients(clients)

    await update.message.reply_text(
        f"Done! {total} records saved from {from_date.isoformat()} to {to_date.isoformat()}."
    )
async def cmd_fetch_wb(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update):
        await update.message.reply_text("❌ This command is admin-only.")
        return

    try:
        from_date, to_date = _parse_fetch_args(update.message.text or "")
    except ValueError as exc:
        await update.message.reply_text(str(exc))
        return

    latest_date = yesterday_local()
    if to_date > latest_date:
        await update.message.reply_text(f"❌ You can only fetch data through {latest_date.isoformat()}.")
        return
    if from_date > to_date:
        await update.message.reply_text("❌ Start date must be on or before the end date.")
        return

    await update.message.reply_text(
        f"⏳ Fetching WB sales data from {from_date.isoformat()} to {to_date.isoformat()}..."
    )

    from shops.wildberries import build_wb_clients
    clients = build_wb_clients(WB_SHOPS)

    if not clients:
        await update.message.reply_text("❌ No WB shops configured. Check WB_A_API_KEY in Railway variables.")
        return

    total = 0
    current_date = from_date
    try:
        while current_date <= to_date:
            for _, client in clients.items():
                try:
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
                    total += len(sales)
                    await update.message.reply_text(
                        f"✅ {client.shop_name} {current_date.isoformat()}: {len(sales)} items saved"
                    )
                except Exception as exc:
                    logger.exception("WB fetch failed for %s on %s", client.shop_id, current_date)
                    await update.message.reply_text(
                        f"❌ {client.shop_name} {current_date.isoformat()} failed: {exc}"
                    )
            current_date += timedelta(days=1)
    finally:
        for client in clients.values():
            await client.close()

    await update.message.reply_text(
        f"Done! {total} WB records saved from {from_date.isoformat()} to {to_date.isoformat()}."
    )
