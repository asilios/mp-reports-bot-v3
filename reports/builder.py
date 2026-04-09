from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

from config import SPIKE_DROP_THRESHOLD
from db.database import fetchall, fetchone
from utils.text import h
from utils.time_utils import today_local

PeriodKey = Literal["today", "yesterday", "week", "month"]


@dataclass(frozen=True)
class PeriodRange:
    key: PeriodKey
    label: str
    start_date: date
    end_date: date


def resolve_period_range(period: PeriodKey) -> PeriodRange:
    today = today_local()
    if period == "today":
        return PeriodRange(period, "Today", today, today)
    if period == "yesterday":
        y = today - timedelta(days=1)
        return PeriodRange(period, "Yesterday", y, y)
    if period == "week":
        start = today - timedelta(days=today.weekday())
        return PeriodRange(period, "This week", start, today)
    if period == "month":
        start = today.replace(day=1)
        return PeriodRange(period, "This month", start, today)
    y = today - timedelta(days=1)
    return PeriodRange("yesterday", "Yesterday", y, y)


def format_money(amount: Decimal | float | int) -> str:
    return f"₽{float(amount):,.0f}"


def get_30day_avgs(shop_id: str, sku_ids: list[str], reference_end_date: date) -> dict[str, float]:
    if not sku_ids:
        return {}

    window_end = reference_end_date - timedelta(days=1)
    window_start = window_end - timedelta(days=29)
    rows = fetchall(
        """
        SELECT sku_id, AVG(units_sold)::float AS avg_units
        FROM sales_history
        WHERE shop_id = %s
          AND sale_date BETWEEN %s AND %s
          AND sku_id = ANY(%s)
        GROUP BY sku_id
        """,
        (shop_id, window_start, window_end, sku_ids),
    )
    return {row["sku_id"]: float(row["avg_units"] or 0.0) for row in rows}


def build_shop_report(shop_id: str, shop_name: str, period: PeriodRange) -> str:
    rows = fetchall(
        """
        SELECT sku_id, sku_name, SUM(units_sold) AS units_sold,
               SUM(revenue) AS revenue, SUM(returns) AS returns
        FROM sales_history
        WHERE shop_id = %s
          AND sale_date BETWEEN %s AND %s
        GROUP BY sku_id, sku_name
        ORDER BY SUM(units_sold) DESC, sku_name ASC
        """,
        (shop_id, period.start_date, period.end_date),
    )

    label = f"{period.label} ({period.start_date.isoformat()})" if period.start_date == period.end_date else (
        f"{period.label} ({period.start_date.isoformat()} → {period.end_date.isoformat()})"
    )

    if not rows:
        return f"🏪 <b>{h(shop_name)}</b>\n<i>No sales data for {h(label)}</i>"

    total_units = sum(int(row["units_sold"] or 0) for row in rows)
    total_revenue = sum(float(row["revenue"] or 0) for row in rows)
    total_returns = sum(int(row["returns"] or 0) for row in rows)

    lines = [
        f"🏪 <b>{h(shop_name)}</b>",
        f"📅 {h(label)}",
        "",
        f"💰 Revenue: <b>{h(format_money(total_revenue))}</b>",
        f"📦 Orders: <b>{total_units}</b> units",
        f"↩️ Returns: <b>{total_returns}</b>",
        "",
        "🏆 <b>Top items:</b>",
    ]

    for row in rows[:5]:
        lines.append(
            f"• {h(row['sku_name'])} — {int(row['units_sold'] or 0)} pcs, {h(format_money(row['revenue'] or 0))}"
        )

    averages = get_30day_avgs(shop_id, [row["sku_id"] for row in rows], period.end_date)
    alerts: list[str] = []
    for row in rows:
        avg = averages.get(row["sku_id"], 0.0)
        units = float(row["units_sold"] or 0)
        if avg <= 0:
            continue
        change = (units - avg) / avg
        if change >= SPIKE_DROP_THRESHOLD:
            alerts.append(f"📈 {h(row['sku_name'])} +{change:.0%} vs 30d avg")
        elif change <= -SPIKE_DROP_THRESHOLD:
            alerts.append(f"📉 {h(row['sku_name'])} {change:.0%} vs 30d avg")

    if alerts:
        lines.extend(["", "⚡️ <b>Unusual activity:</b>", *alerts[:8]])

    return "\n".join(lines)


def build_united_report(shop_names: dict[str, str], period: PeriodRange) -> str:
    rows = fetchall(
        """
        SELECT shop_id,
               SUM(units_sold) AS units,
               SUM(revenue) AS revenue,
               SUM(returns) AS returns
        FROM sales_history
        WHERE sale_date BETWEEN %s AND %s
        GROUP BY shop_id
        ORDER BY SUM(revenue) DESC NULLS LAST, shop_id ASC
        """,
        (period.start_date, period.end_date),
    )

    label = f"{period.label} ({period.start_date.isoformat()})" if period.start_date == period.end_date else (
        f"{period.label} ({period.start_date.isoformat()} → {period.end_date.isoformat()})"
    )

    if not rows:
        return f"📊 <b>United Report</b>\n<i>No data for {h(label)}</i>"

    grand_units = sum(int(row["units"] or 0) for row in rows)
    grand_revenue = sum(float(row["revenue"] or 0) for row in rows)
    grand_returns = sum(int(row["returns"] or 0) for row in rows)

    lines = [
        "📊 <b>United Report — All Shops</b>",
        f"📅 {h(label)}",
        "",
        f"💰 Total revenue: <b>{h(format_money(grand_revenue))}</b>",
        f"📦 Total orders: <b>{grand_units}</b> units",
        f"↩️ Total returns: <b>{grand_returns}</b>",
        "",
    ]

    for row in rows:
        shop_name = shop_names.get(row["shop_id"], row["shop_id"])
        lines.append(
            f"🏪 <b>{h(shop_name)}</b>: {h(format_money(row['revenue'] or 0))} | {int(row['units'] or 0)} orders"
        )

    best = fetchone(
        """
        SELECT sku_name, SUM(units_sold) AS total
        FROM sales_history
        WHERE sale_date BETWEEN %s AND %s
        GROUP BY sku_name
        ORDER BY SUM(units_sold) DESC, sku_name ASC
        LIMIT 1
        """,
        (period.start_date, period.end_date),
    )
    if best:
        lines.extend(["", f"🏆 Best seller: <b>{h(best['sku_name'])}</b> ({int(best['total'] or 0)} units)"])

    return "\n".join(lines)
