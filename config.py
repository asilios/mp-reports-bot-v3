import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class ShopConfig:
    name: str
    client_id: str | None = None
    api_key: str | None = None


BOT_TOKEN = os.getenv("BOT_TOKEN")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")
DATABASE_URL = os.getenv("DATABASE_URL")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Tashkent")

ADMIN_USER_IDS = {
    int(raw.strip())
    for raw in os.getenv("ADMIN_USER_IDS", "").split(",")
    if raw.strip().isdigit()
}

LOW_STOCK_THRESHOLD = int(os.getenv("LOW_STOCK_THRESHOLD", "10"))
SPIKE_DROP_THRESHOLD = float(os.getenv("SPIKE_DROP_THRESHOLD", "0.50"))
REVIEW_CHECK_HOURS = int(os.getenv("REVIEW_CHECK_HOURS", "2"))
STOCK_CHECK_HOURS = int(os.getenv("STOCK_CHECK_HOURS", "6"))

DAILY_REPORT_HOUR = int(os.getenv("DAILY_REPORT_HOUR", "9"))
DAILY_REPORT_MINUTE = int(os.getenv("DAILY_REPORT_MINUTE", "0"))

OZON_SHOPS: dict[str, dict[str, str | None]] = {
    "ozon_a": {
        "name": os.getenv("OZON_A_NAME", "Ozon Shop A"),
        "client_id": os.getenv("OZON_A_CLIENT_ID"),
        "api_key": os.getenv("OZON_A_API_KEY"),
    },
    "ozon_b": {
        "name": os.getenv("OZON_B_NAME", "Ozon Shop B"),
        "client_id": os.getenv("OZON_B_CLIENT_ID"),
        "api_key": os.getenv("OZON_B_API_KEY"),
    },
}

WB_SHOPS: dict[str, dict[str, str | None]] = {}

ALL_SHOPS = {**OZON_SHOPS, **WB_SHOPS}


def validate_config() -> None:
    missing: list[str] = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not GROUP_CHAT_ID:
        missing.append("GROUP_CHAT_ID")
    if not DATABASE_URL:
        missing.append("DATABASE_URL")
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
