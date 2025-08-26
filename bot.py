import os
import time
import logging
import requests
from typing import Optional

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ---- Configuration via environment variables ----
# Set these in Render's dashboard (or locally in your shell):
#   export BOT_TOKEN="123456:ABC..."
#   export BLOCK_ID="123456"
BOT_TOKEN = os.getenv("7016999277:AAEa5b_-_AxuhXp1U6JeP_eO822ORHHc0L4")
BLOCK_ID = os.getenv("int-14249")  # numeric Block ID from AdsGram
AD_API = "https://api.adsgram.ai/advbot"

# Basic validation early so it fails fast if not configured
if not BOT_TOKEN:
    raise RuntimeError("Missing BOT_TOKEN env var")
if not BLOCK_ID or not BLOCK_ID.isdigit():
    raise RuntimeError("BLOCK_ID must be numeric and set as env var")

# ---- Logging (helpful on Render logs) ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("adsgram-bot")

# ---- Simple anti-spam: 1 ad per user per N seconds ----
COOLDOWN_SECONDS = 8
_last_ad_at: dict[int, float] = {}  # user_id -> timestamp


def _cooldown_ok(user_id: int) -> bool:
    now = time.time()
    last = _last_ad_at.get(user_id, 0)
    if now - last >= COOLDOWN_SECONDS:
        _last_ad_at[user_id] = now
        return True
    return False


def _fetch_ad(tgid: int) -> Optional[dict]:
    """
    Calls AdsGram API for a single ad for this Telegram user id.
    Returns parsed JSON dict on success, or None on failure/no fill.
    """
    url = f"{AD_API}?tgid={tgid}&blockid={BLOCK_ID}"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            log.warning("AdsGram non-200: %s %s", resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        # Some responses may include an error or be empty — handle gracefully.
        if not isinstance(data, dict) or not data.get("button_name"):
            log.info("No ad / malformed ad: %s", str(data)[:200])
            return None
        return data
    except Exception as e:
        log.exception("Failed to fetch ad: %s", e)
        return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Greets the user and shows a 'Show Ads' button.
    """
    keyboard = [[InlineKeyboardButton("📣 Show Ads", callback_data="show_ads")]]
    await update.message.reply_text(
        "👋 Welcome! Tap the button to view a sponsored ad and support the bot.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n"
        "/ads — show a sponsored ad\n"
        "/start — get the welcome message with a button"
    )


async def show_ads_common(update, context, *, reply_target):
    """
    Shared logic to fetch and display an ad.
    `reply_target` is either a Message (for /ads) or CallbackQuery.message (for button).
    """
    user_id = update.effective_user.id

    # Cooldown
    if not _cooldown_ok(user_id):
        await reply_target.reply_text("⏳ Please wait a few seconds before requesting another ad.")
        return

    ad = _fetch_ad(user_id)
    if not ad:
        await reply_target.reply_text("😕 No ad available right now. Please try again shortly.")
        return

    # Build inline buttons
    buttons = [[InlineKeyboardButton(ad["button_name"], url=ad.get("click_url", "https://t.me"))]]
    # Rewarded fields may be present; add if available
    if ad.get("button_reward_name") and ad.get("reward_url"):
        buttons.append([InlineKeyboardButton(ad["button_reward_name"], url=ad["reward_url"])])

    markup = InlineKeyboardMarkup(buttons)

    # Prefer image+caption if provided; else plain text
    text_html = ad.get("text_html") or "Sponsored"
    image_url = ad.get("image_url")

    if image_url:
        await reply_target.reply_photo(
            photo=image_url,
            caption=text_html,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            protect_content=True,  # AdsGram recommends disabling forwards
        )
    else:
        await reply_target.reply_text(
            text_html,
            parse_mode=ParseMode.HTML,
            reply_markup=markup,
            protect_content=True,
        )


async def ads_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await show_ads_common(update, context, reply_target=update.message)


async def button_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles the '📣 Show Ads' button.
    """
    query = update.callback_query
    await query.answer()
    if query.data == "show_ads":
        await show_ads_common(update, context, reply_target=query.message)


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("ads", ads_cmd))
    app.add_handler(CallbackQueryHandler(button_cb))

    log.info("Bot starting…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()