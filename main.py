import os
import logging
import threading
from datetime import datetime
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
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

PHOTO_COLUMN_NAME = "Зображення"

notion = Client(auth=NOTION_TOKEN)

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
    if not prop_data:
        return "—"
    
    prop_type = prop_data.get("type")

    if prop_type == "title" and prop_data.get("title"):
        return "".join([t.get("plain_text", "") for t in prop_data["title"]]) or "—"
    
    elif prop_type == "rich_text" and prop_data.get("rich_text"):
        return "".join([t.get("plain_text", "") for t in prop_data["rich_text"]]) or "—"
    
    elif prop_type == "number" and prop_data.get("number") is not None:
        val = prop_data.get("number")
        if isinstance(val, float) and val.is_integer():
            return str(int(val))
        return str(val)
    
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
    if PHOTO_COLUMN_NAME in properties:
        img_prop = properties[PHOTO_COLUMN_NAME]
        img_type = img_prop.get("type")
        
        url_val = None
        if img_type == "url":
            url_val = img_prop.get("url")
        elif img_type == "rich_text":
            url_val = "".join([t.get("plain_text", "") for t in img_prop.get("rich_text", [])])
        elif img_type == "title":
            url_val = "".join([t.get("plain_text", "") for t in img_prop.get("title", [])])
            
        if url_val and ("http://" in url_val or "https://" in url_val):
            return url_val.strip()

    if "Photo" in properties:
        prop = properties["Photo"]
        p_type = prop.get("type")
        if p_type == "url" and prop.get("url"):
            return prop.get("url")
        elif p_type == "files" and prop.get("files"):
            files = prop.get("files")
            if files:
                first_file = files[0]
                if first_file.get("type") == "external":
                    return first_file.get("external", {}).get("url")

    return None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привіт! 👋\n\nЯ допоможу знайти інформацію про товар у базі Notion.\nПросто надішліть код **EAN**.",
        parse_mode="Markdown"
    )

async def search_notion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_text = update.message.text.strip()
    if not query_text:
        return

    user = update.message.from_user
    username = f"@{user.username}" if user.username else f"{user.first_name or ''} {user.last_name or ''}".strip()
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Надсилаємо статистику як простий текст (без parse_mode, щоб уникнути помилок форматування)
    if LOG_CHANNEL_ID:
        try:
            log_text = f"📊 Запит до бота\n• Час: {current_time}\n• Користувач: {username} (ID: {user.id})\n• Запит (EAN): {query_text}"
            await context.bot.send_message(chat_id=LOG_CHANNEL_ID, text=log_text)
        except Exception as log_err:
            logging.warning(f"Не вдалося надіслати лог у канал: {log_err}")

    await update.message.reply_text(f"🔍 Шукаю: «{query_text}»...")

    try:
        try:
            query_number = float(query_text)
        except ValueError:
            query_number = 0.0

        results = notion.databases.query(
            database_id=DATABASE_ID,
            filter={
                "property": "EAN",
                "number": {"equals": query_number}
            }
        )

        pages = results.get("results", [])

        if not pages:
            await update.message.reply_text("Нічого не знайдено 😔")
            return

        for page in pages:
            properties = page.get("properties", {})

            image_url = extract_image_url(properties)
            if image_url:
                try:
                    await update.message.reply_photo(photo=image_url)
                except Exception as img_err:
                    logging.warning(f"Не вдалося відправити зображення ({image_url}): {img_err}")

            priority_keys = [
                "EAN",
                "Опис",
                "Залишок",
                "Кратність, шт."
            ]
            
            message_lines = []

            for key in priority_keys:
                if key in properties:
                    val = extract_property_value(properties[key])
                    if val != "—":
                        message_lines.append(f"• **{key}:** {val}")

            for prop_name, prop_data in properties.items():
                if prop_name not in priority_keys and prop_name != PHOTO_COLUMN_NAME and prop_name != "Photo":
                    val = extract_property_value(prop_data)
                    if val != "—":
                        if "http://" in val or "https://" in val:
                            continue
                        message_lines.append(f"• **{prop_name}:** {val}")

            full_message = "\n".join(message_lines)

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
