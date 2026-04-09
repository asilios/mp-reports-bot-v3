from __future__ import annotations

import logging

from config import LOW_STOCK_THRESHOLD
from db.database import execute, executemany, fetchall
from utils.text import h
from utils.time_utils import now_local

logger = logging.getLogger(__name__)


async def check_low_stock(clients: dict, bot, chat_id: str) -> None:
    now = now_local()
    for shop_id, client in clients.items():
        stock_items = await client.get_stock_levels()
        if stock_items is None:
            logger.warning("[%s] Could not fetch stock levels", shop_id)
            continue

        executemany(
            """
            INSERT INTO stock_levels (shop_id, sku_id, sku_name, stock, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (shop_id, sku_id)
            DO UPDATE SET
                sku_name = EXCLUDED.sku_name,
                stock = EXCLUDED.stock,
                updated_at = EXCLUDED.updated_at
            """,
            [
                (shop_id, item["sku_id"], item["sku_name"], int(item["stock"]), now)
                for item in stock_items
            ],
        )

        low_items = [item for item in stock_items if int(item["stock"]) < LOW_STOCK_THRESHOLD]
        current_low_skus = {item["sku_id"] for item in low_items}

        if not low_items:
            execute("DELETE FROM low_stock_notified WHERE shop_id = %s", (shop_id,))
            continue

        already_rows = fetchall("SELECT sku_id FROM low_stock_notified WHERE shop_id = %s", (shop_id,))
        already_notified = {row["sku_id"] for row in already_rows}

        execute(
            "DELETE FROM low_stock_notified WHERE shop_id = %s AND sku_id <> ALL(%s)",
            (shop_id, list(current_low_skus)),
        )

        new_low = [item for item in low_items if item["sku_id"] not in already_notified]
        if not new_low:
            continue

        lines = [f"⚠️ <b>Low stock — {h(client.shop_name)}</b>", ""]
        for item in new_low[:25]:
            lines.append(f"• {h(item['sku_name'])} — <b>{int(item['stock'])}</b> units left")
        lines.extend(["", "<i>Restock soon to avoid lost sales.</i>"])
        await bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="HTML")

        executemany(
            """
            INSERT INTO low_stock_notified (shop_id, sku_id, notified_at)
            VALUES (%s, %s, %s)
            ON CONFLICT (shop_id, sku_id)
            DO UPDATE SET notified_at = EXCLUDED.notified_at
            """,
            [(shop_id, item["sku_id"], now) for item in new_low],
        )
        logger.info("[%s] Low stock alert sent for %s items", shop_id, len(new_low))


async def check_bad_reviews(clients: dict, bot, chat_id: str) -> None:
    for shop_id, client in clients.items():
        reviews = await client.get_reviews(limit=50)
        bad_reviews = [review for review in reviews if int(review.get("rating", 0) or 0) <= 2]
        if not bad_reviews:
            continue

        seen_rows = fetchall("SELECT review_id FROM seen_reviews WHERE shop_id = %s", (shop_id,))
        seen_ids = {row["review_id"] for row in seen_rows}
        new_bad = [review for review in bad_reviews if review["review_id"] not in seen_ids]
        if not new_bad:
            continue

        for review in new_bad[:10]:
            rating = int(review.get("rating", 0) or 0)
            preview = (review.get("text") or "").strip()
            if len(preview) > 300:
                preview = preview[:297] + "..."
            msg = (
                f"{'⭐️' * max(rating, 0)} <b>New {rating}-star review — {h(client.shop_name)}</b>\n"
                f"📦 Item: {h(review.get('sku_name', 'Unknown item'))}\n\n"
                f"<i>{h(preview or 'No review text provided')}</i>"
            )
            await bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")

        executemany(
            """
            INSERT INTO seen_reviews (shop_id, review_id, rating, created_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (shop_id, review_id) DO NOTHING
            """,
            [
                (
                    shop_id,
                    review["review_id"],
                    int(review.get("rating", 0) or 0),
                    review.get("created_at") or None,
                )
                for review in new_bad
            ],
        )
        logger.info("[%s] Bad review alert sent for %s reviews", shop_id, len(new_bad))
