from telegram import Bot

TOKEN = "PASTE_YOUR_TELEGRAM_BOT_TOKEN_HERE"  # 🔁 Nhớ thay token thật của bạn
bot = Bot(token=TOKEN)

bot.delete_webhook(drop_pending_updates=True)
print("✅ Webhook & polling cũ đã được xóa khỏi Telegram.")
