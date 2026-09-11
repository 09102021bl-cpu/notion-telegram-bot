import os
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from notion_client import Client

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_ID = os.getenv("DATABASE_ID")

notion = Client(auth=NOTION_TOKEN)

# Простий заглушечний сервер для Render (щоб пройти Health Check)
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_dummy_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привіт! Надішли мені код EAN10 або EAN40 для пошуку в Notion."
    )

async def search_notion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_text = update.message.text.strip()
    if not query_text:
        return

    await update.message.reply_text(f"🔍 Шукаю: «{query_text}»...")

    try:
        # Використовуємо стандартний databases.query
        results = notion.databases.query(
            database_id=DATABASE_ID,
            filter={
                "or": [
                    {"property": "EAN10", "rich_text": {"contains": query_text}},
                    {"property": "EAN40", "rich_text": {"contains": query_text}},
                    {"property": "EAN10", "title": {"contains": query_text}},
                    {"property": "EAN40", "title": {"contains": query_text}}
                ]
            }
        )

        pages = results.get("results", [])

        if not pages:
            await update.message.reply_text("Нічого не знайдено 😔")
            return

        response = "Знайдено такі записи:\n\n"
        for page in pages:
            properties = page.get("properties", {})
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
        await update.message.reply_text(f"Помилка від Notion API:\n`{e}`", parse_mode="Markdown")

if __name__ == "__main__":
    # Запуск фонового веб-сервера для Render
    threading.Thread(target=run_dummy_server, daemon=True).start()
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_notion))
    app.run_polling()
