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

# Точна назва колонки в Notion, де зберігається URL-посилання на фото
PHOTO_COLUMN_NAME = "Зображення"  

notion = Client(auth=NOTION_TOKEN)

# Фоновий веб-сервер для проходження Health Check на Render
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

def run_dummy_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

def extract_property_value(prop_data):
    """Обробляє різні типи полів Notion та повертає їх текстове значення."""
    if not prop_data:
        return "—"
    
    prop_type = prop_data.get("type")

    if prop_type == "title" and prop_data.get("title"):
        return "".join([t.get("plain_text", "") for t in prop_data["title"]]) or "—"
    
    elif prop_type == "rich_text" and prop_data.get("rich_text"):
        return "".join([t.get("plain_text", "") for t in prop_data["rich_text"]]) or "—"
    
    elif prop_type == "number" and prop_data.get("number") is not None:
        return str(prop_data.get("number"))
    
    elif prop_type == "select" and prop_data.get("select"):
        return prop_data["select"].get("name", "—")
    
    elif prop_type == "multi_select" and prop_data.get("multi_select"):
        return ", ".join([item.get("name", "") for item in prop_data["multi_select"]]) or "—"
    
    elif prop_type == "url" and prop_data.get("url"):
        return prop_data.get("url")
    
    elif prop_type == "checkbox":
        return "Так" if prop_data.get("checkbox") else "Ні"
    
    elif prop_type == "date" and prop_data.get("date"):
        return prop_data["date"].get("start", "—")

    return "—"

def extract_image_url(properties):
    """Отримує прямий URL зображення з Notion (тип URL або Files & Media)."""
    # 1. Шукаємо спочатку у вказаній колонці
    if PHOTO_COLUMN_NAME in properties:
        prop = properties[PHOTO_COLUMN_NAME]
        p_type = prop.get("type")
        
        if p_type == "url" and prop.get("url"):
            return prop.get("url")
        
        elif p_type == "files" and prop.get("files"):
            files = prop.get("files")
            if files:
                first_file = files[0]
                if first_file.get("type") == "external":
                    return first_file.get("external", {}).get("url")
                elif first_file.get("type") == "file":
                    return first_file.get("file", {}).get("url")

    # 2. Якщо в точній колонці не знайшли, перевіряємо інші URL/Files поля
    for prop_name, prop in properties.items():
        p_type = prop.get("type")
        if p_type == "url" and prop.get("url"):
            url = prop.get("url")
            if any(url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']):
                return url
        elif p_type == "files" and prop.get("files"):
            files = prop.get("files")
            if files:
                first_file = files[0]
                if first_file.get("type") == "external":
                    return first_file.get("external", {}).get("url")
                elif first_file.get("type") == "file":
                    return first_file.get("file", {}).get("url")

    return None

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

        for page in pages:
            properties = page.get("properties", {})

            # 1. Спочатку шукаємо та відправляємо ФОТО за посиланням
            image_url = extract_image_url(properties)
            if image_url:
                try:
                    await update.message.reply_photo(photo=image_url)
                except Exception as img_err:
                    logging.warning(f"Не вдалося відправити зображення: {img_err}")

            # 2. Формуємо ТЕКСТ (EAN10 -> EAN40 -> решта полів)
            priority_keys = ["EAN10", "EAN40"]
            message_lines = []

            # Додаємо EAN10 та EAN40
            for key in priority_keys:
                if key in properties:
                    val = extract_property_value(properties[key])
                    if val != "—":
                        message_lines.append(f"• **{key}:** {val}")

            # Додаємо всі інші поля (окрім колонки з фото, щоб не дублювати URL)
            for prop_name, prop_data in properties.items():
                if prop_name not in priority_keys and prop_name != PHOTO_COLUMN_NAME:
                    val = extract_property_value(prop_data)
                    if val != "—":
                        message_lines.append(f"• **{prop_name}:** {val}")

            full_message = "\n".join(message_lines)

            # Відправляємо окреме текстове повідомлення
            if full_message:
                await update.message.reply_text(
                    full_message, 
                    parse_mode="Markdown", 
                    disable_web_page_preview=True
                )

    except Exception as e:
        logging.error(f"Помилка при пошуку: {e}")
        await update.message.reply_text(f"Помилка від Notion API:\n`{e}`", parse_mode="Markdown")

if __name__ == "__main__":
    threading.Thread(target=run_dummy_server, daemon=True).start()
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, search_notion))
    app.run_polling()
