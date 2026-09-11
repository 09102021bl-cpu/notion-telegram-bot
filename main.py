import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from notion_client import Client

# Налаштування логування
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Отримання ключів зі змінних оточення
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_ID = os.getenv("DATABASE_ID")

# Ініціалізація клієнта Notion
notion = Client(auth=NOTION_TOKEN)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    await update.message.reply_text(
        "Привіт! Надішли мені код EAN10 або EAN40 для пошуку в базі даних Notion."
    )

async def search_notion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Пошук у базі даних Notion за колонками EAN10 або EAN40"""
    query_text = update.message.text.strip()
    
    if not query_text:
        return

    await update.message.reply_text(f"🔍 Шукаю: «{query_text}»...")

    try:
        # Запит до Notion API (пошук в EAN10 АБО в EAN40)
        results = notion.databases.query(
            **{
                "database_id": DATABASE_ID,
                "filter": {
                    "or": [
                        {
                            "property": "EAN10",
                            "rich_text": {
                                "contains": query_text
                            }
                        },
                        {
                            "property": "EAN40",
                            "rich_text": {
                                "contains": query_text
                            }
                        }
                    ]
                }
            }
        )

        pages = results.get("results", [])

        if not pages:
            await update.message.reply_text("Нічого не знайдено 😔")
            return

        response = "Знайдено такі записи:\n\n"
        for page in pages:
            properties = page.get("properties", {})
            
            # Отримання назви сторінки (Title)
            title = "Запис знайдено"
            for prop_name, prop_data in properties.items():
                if prop_data.get("type") == "title" and prop_data.get("title"):
                    if len(prop_data["title"]) > 0:
                        title = prop_data["title"][0]["text"]["content"]
                    break

            url = page.get("url", "")
            response += f"• [{title}]({url})\n"

        await update.message.reply_text(response, parse_mode="Markdown", disable_web_page_preview=True)

    except Exception as e:
        logging.error(f"Помилка при пошуку: {e}")
        await update.message.reply_text("Виникла помилка під час запиту до Notion. Перевірте, чи існують колонки EAN10 та EAN40 у вашій таблиці.")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_notion))
    
    app.run_polling()
