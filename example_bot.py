"""
Sample Telegram Bot — para i-test ang BotHost platform.
I-upload mo ito sa dashboard kasama ang iyong real BOT TOKEN.

Para gumawa ng Telegram bot token:
1. Buksan ang Telegram → hanapin ang @BotFather
2. I-type: /newbot
3. Sundin ang instructions → makakakuha ka ng token
4. I-paste ang token sa BotHost dashboard

Requirements (awtomatikong naka-install sa server):
  pip install pyTelegramBotAPI
"""

import os
import telebot

TOKEN = os.environ.get("BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")

if not TOKEN:
    raise ValueError("❌ Walang BOT_TOKEN! I-set mo sa BotHost dashboard.")

bot = telebot.TeleBot(TOKEN)
print(f"✅ Bot started! Token: {TOKEN[:10]}...")


@bot.message_handler(commands=["start", "hello"])
def send_welcome(message):
    name = message.from_user.first_name
    bot.reply_to(message, f"👋 Kumusta, {name}!\n\nAko ay bot na naka-host sa BotHost.\n\nMga commands:\n/start — Welcome message\n/help — Tulong\n/echo [text] — Uulitin ang sinabi mo\n/info — Info tungkol sa bot")
    print(f"💬 /start mula kay @{message.from_user.username}")


@bot.message_handler(commands=["help"])
def send_help(message):
    help_text = (
        "🤖 *BotHost Sample Bot*\n\n"
        "Available commands:\n"
        "/start — Welcome\n"
        "/help — Ito\n"
        "/echo [text] — Uulitin ko ang text\n"
        "/info — Server info\n\n"
        "Gawin mong base ito para sa sarili mong bot!"
    )
    bot.reply_to(message, help_text, parse_mode="Markdown")


@bot.message_handler(commands=["echo"])
def echo(message):
    parts = message.text.split(" ", 1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /echo [message]")
        return
    bot.reply_to(message, parts[1])
    print(f"🔄 Echo: {parts[1]}")


@bot.message_handler(commands=["info"])
def bot_info(message):
    import platform, sys
    info = (
        f"🖥 *Server Info*\n"
        f"Python: {sys.version.split()[0]}\n"
        f"OS: {platform.system()} {platform.release()}\n"
        f"Bot: @{bot.get_me().username}"
    )
    bot.reply_to(message, info, parse_mode="Markdown")


@bot.message_handler(func=lambda m: True)
def handle_all(message):
    bot.reply_to(message, f"Sinabi mo: {message.text}\n\nI-type ang /help para sa mga commands.")


print("📡 Polling for messages...")
bot.infinity_polling(timeout=30, long_polling_timeout=20)
