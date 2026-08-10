import os
import logging
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest
import httpx

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot token from environment variable
TOKEN = os.environ.get("TELEGRAM_TOKEN")
if not TOKEN:
    logger.error("TELEGRAM_TOKEN environment variable not set!")
    exit(1)

# File to store anniversaries
DATA_FILE = "anniversaries.json"

# Default data structure
DEFAULT_DATA = {
    "anniversaries": [],
    "subscribers": []
}

# Load or initialize data
def load_data():
    try:
        if Path(DATA_FILE).exists():
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        return DEFAULT_DATA.copy()
    except Exception as e:
        logger.error(f"Error loading data: {e}")
        return DEFAULT_DATA.copy()

def save_data(data):
    try:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error saving data: {e}")

# Anniversary manager
class AnniversaryManager:
    def __init__(self):
        self.data = load_data()
        
    def add_anniversary(self, name, day, month, year=None, chat_id=None):
        entry = {
            "id": len(self.data["anniversaries"]) + 1,
            "name": name,
            "day": int(day),
            "month": int(month),
            "year": int(year) if year else None,
            "chat_id": str(chat_id) if chat_id else None
        }
        self.data["anniversaries"].append(entry)
        save_data(self.data)
        return entry
    
    def remove_anniversary(self, anniv_id):
        self.data["anniversaries"] = [a for a in self.data["anniversaries"] if a["id"] != anniv_id]
        save_data(self.data)
    
    def get_today_anniversaries(self):
        today = datetime.now()
        today_annivs = []
        for anniv in self.data["anniversaries"]:
            if anniv["day"] == today.day and anniv["month"] == today.month:
                if anniv["year"]:
                    if anniv["year"] == today.year:
                        today_annivs.append(anniv)
                else:
                    today_annivs.append(anniv)
        return today_annivs
    
    def get_upcoming_anniversaries(self, days_ahead=7):
        today = datetime.now()
        upcoming = []
        for anniv in self.data["anniversaries"]:
            try:
                anniv_date = datetime(today.year, anniv["month"], anniv["day"])
                if anniv_date < today:
                    anniv_date = datetime(today.year + 1, anniv["month"], anniv["day"])
                days_until = (anniv_date - today).days
                if 0 <= days_until <= days_ahead:
                    upcoming.append((anniv, days_until))
            except ValueError:
                continue
        return sorted(upcoming, key=lambda x: x[1])
    
    def get_anniversary_by_id(self, anniv_id):
        for anniv in self.data["anniversaries"]:
            if anniv["id"] == anniv_id:
                return anniv
        return None
    
    def get_all_anniversaries(self):
        return self.data["anniversaries"]
    
    def add_subscriber(self, chat_id):
        chat_id_str = str(chat_id)
        if chat_id_str not in self.data["subscribers"]:
            self.data["subscribers"].append(chat_id_str)
            save_data(self.data)
            return True
        return False
    
    def remove_subscriber(self, chat_id):
        chat_id_str = str(chat_id)
        if chat_id_str in self.data["subscribers"]:
            self.data["subscribers"].remove(chat_id_str)
            save_data(self.data)
            return True
        return False
    
    def get_subscribers(self):
        return self.data["subscribers"]

manager = AnniversaryManager()

# ----- COMMAND HANDLERS -----

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🎉 Hello {user.first_name}!\n\n"
        "I'm **AnniversarysBot** - your personal anniversary reminder! 🎂\n\n"
        "📌 **Commands:**\n"
        "/add - Add a new anniversary\n"
        "/list - List all saved anniversaries\n"
        "/remove - Remove an anniversary\n"
        "/today - Check today's anniversaries\n"
        "/upcoming - Check anniversaries in the next 7 days\n"
        "/subscribe - Get daily notifications\n"
        "/unsubscribe - Stop notifications\n"
        "/help - Show this message",
        parse_mode="Markdown"
    )

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)

async def add_anniversary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        try:
            args = context.args
            if len(args) < 3:
                await update.message.reply_text(
                    "❌ Format: `/add Name DD MM YYYY`\n"
                    "Example: `/add Wedding 15 06 2022`"
                )
                return
            
            # Find numbers in args
            numbers = []
            words = []
            for arg in args:
                if arg.isdigit():
                    numbers.append(int(arg))
                else:
                    words.append(arg)
            
            if len(numbers) < 2:
                await update.message.reply_text("❌ Please provide day and month.")
                return
            
            name = " ".join(words) if words else "Anniversary"
            day = numbers[0]
            month = numbers[1]
            year = numbers[2] if len(numbers) > 2 else None
            
            if 1 <= day <= 31 and 1 <= month <= 12:
                manager.add_anniversary(name, day, month, year, update.effective_chat.id)
                year_text = f" in {year}" if year else " (recurring)"
                await update.message.reply_text(
                    f"✅ Added: **{name}** on {day}/{month}{year_text}!"
                )
                return
            else:
                await update.message.reply_text("❌ Invalid date!")
                return
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}")
            return
    
    # Interactive mode
    context.user_data["awaiting_add"] = True
    await update.message.reply_text(
        "📝 Send details: `Name, DD, MM, YYYY`\n"
        "Example: `Wedding, 15, 06, 2022`\n"
        "Send /cancel to cancel",
        parse_mode="Markdown"
    )

async def handle_add_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_add"):
        return
    
    text = update.message.text
    if text == "/cancel":
        context.user_data["awaiting_add"] = False
        await update.message.reply_text("❌ Cancelled.")
        return
    
    try:
        parts = [p.strip() for p in text.split(",")]
        if len(parts) < 3 or len(parts) > 4:
            await update.message.reply_text("❌ Use: `Name, DD, MM, YYYY`")
            return
        
        name = parts[0]
        day = int(parts[1])
        month = int(parts[2])
        year = int(parts[3]) if len(parts) == 4 else None
        
        if 1 <= day <= 31 and 1 <= month <= 12:
            manager.add_anniversary(name, day, month, year, update.effective_chat.id)
            year_text = f" in {year}" if year else " (recurring)"
            await update.message.reply_text(f"✅ Added: **{name}** on {day}/{month}{year_text}!")
            context.user_data["awaiting_add"] = False
        else:
            await update.message.reply_text("❌ Invalid date!")
    except ValueError:
        await update.message.reply_text("❌ Invalid format! Use: `Name, DD, MM, YYYY`")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def list_anniversaries(update: Update, context: ContextTypes.DEFAULT_TYPE):
    anniversaries = manager.get_all_anniversaries()
    chat_id = str(update.effective_chat.id)
    
    chat_annivs = [a for a in anniversaries if a.get("chat_id") == chat_id or a.get("chat_id") is None]
    
    if not chat_annivs:
        await update.message.reply_text("📭 No anniversaries saved!")
        return
    
    message = "📋 **Your Anniversaries:**\n\n"
    for anniv in chat_annivs:
        year_text = f" ({anniv['year']})" if anniv.get("year") else " (recurring)"
        message += f"🆔 {anniv['id']}: **{anniv['name']}** - {anniv['day']}/{anniv['month']}{year_text}\n"
    
    message += "\n📌 Use `/remove ID` to delete."
    await update.message.reply_text(message, parse_mode="Markdown")

async def remove_anniversary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Provide ID: `/remove 1`")
        return
    
    try:
        anniv_id = int(context.args[0])
        anniv = manager.get_anniversary_by_id(anniv_id)
        
        if anniv:
            chat_id = str(update.effective_chat.id)
            if anniv.get("chat_id") and anniv["chat_id"] != chat_id:
                await update.message.reply_text("❌ Not your anniversary.")
                return
            
            manager.remove_anniversary(anniv_id)
            await update.message.reply_text(f"✅ Removed: **{anniv['name']}**")
        else:
            await update.message.reply_text("❌ Not found.")
    except ValueError:
        await update.message.reply_text("❌ Invalid ID.")

async def today_anniversaries(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today_annivs = manager.get_today_anniversaries()
    chat_id = str(update.effective_chat.id)
    
    chat_annivs = [a for a in today_annivs if a.get("chat_id") == chat_id or a.get("chat_id") is None]
    
    if not chat_annivs:
        await update.message.reply_text("🎉 No anniversaries today!")
        return
    
    message = "🎊 **Today's Anniversaries:**\n\n"
    for anniv in chat_annivs:
        year_text = f" ({anniv['year']})" if anniv.get("year") else ""
        message += f"🎂 **{anniv['name']}** - {anniv['day']}/{anniv['month']}{year_text}\n"
    
    await update.message.reply_text(message, parse_mode="Markdown")

async def upcoming_anniversaries(update: Update, context: ContextTypes.DEFAULT_TYPE):
    days_ahead = 7
    if context.args:
        try:
            days_ahead = int(context.args[0])
        except ValueError:
            days_ahead = 7
    
    upcoming = manager.get_upcoming_anniversaries(days_ahead)
    chat_id = str(update.effective_chat.id)
    
    chat_upcoming = [(a, d) for a, d in upcoming if a.get("chat_id") == chat_id or a.get("chat_id") is None]
    
    if not chat_upcoming:
        await update.message.reply_text(f"📅 No anniversaries in next {days_ahead} days!")
        return
    
    message = f"📅 **Upcoming ({days_ahead} days):**\n\n"
    for anniv, days in chat_upcoming:
        year_text = f" ({anniv['year']})" if anniv.get("year") else ""
        if days == 0:
            day_text = "**🎉 TODAY!**"
        elif days == 1:
            day_text = "Tomorrow"
        else:
            day_text = f"In {days} days"
        message += f"• **{anniv['name']}** - {day_text}\n"
    
    await update.message.reply_text(message, parse_mode="Markdown")

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if manager.add_subscriber(chat_id):
        await update.message.reply_text("✅ **Subscribed!** I'll send daily reminders at 9:00 AM.")
    else:
        await update.message.reply_text("ℹ️ Already subscribed!")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if manager.remove_subscriber(chat_id):
        await update.message.reply_text("✅ Unsubscribed.")
    else:
        await update.message.reply_text("ℹ️ Not subscribed.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    anniversaries = manager.get_all_anniversaries()
    subscribers = manager.get_subscribers()
    
    message = f"📊 **Stats:**\n\n"
    message += f"📝 Anniversaries: {len(anniversaries)}\n"
    message += f"👥 Subscribers: {len(subscribers)}\n"
    message += f"⏰ Daily notifications: 9:00 AM"
    
    await update.message.reply_text(message, parse_mode="Markdown")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Error: {context.error}")
    if update and update.effective_message:
        try:
            await update.effective_message.reply_text(
                "❌ An error occurred. The bot will try to recover."
            )
        except:
            pass

# ----- DAILY REMINDER -----

async def send_daily_reminders(context: ContextTypes.DEFAULT_TYPE):
    try:
        today_annivs = manager.get_today_anniversaries()
        if not today_annivs:
            return
        
        subscribers = manager.get_subscribers()
        
        for chat_id in subscribers:
            try:
                chat_annivs = [a for a in today_annivs if a.get("chat_id") == chat_id or a.get("chat_id") is None]
                
                if chat_annivs:
                    message = "🌅 **Good Morning! Today's Anniversaries:** 🎉\n\n"
                    for anniv in chat_annivs:
                        year_text = f" ({anniv['year']})" if anniv.get("year") else ""
                        message += f"🎂 **{anniv['name']}** - {anniv['day']}/{anniv['month']}{year_text}\n"
                    message += "\n🎊 Celebrate and make it special!"
                    
                    await context.bot.send_message(chat_id=int(chat_id), text=message, parse_mode="Markdown")
                    await asyncio.sleep(0.5)  # Avoid rate limits
            except Exception as e:
                logger.error(f"Failed to send to {chat_id}: {e}")
    except Exception as e:
        logger.error(f"Daily reminder error: {e}")

# ----- MAIN -----

def main():
    """Start the bot with timeout handling"""
    try:
        # Create custom HTTP client with timeout and retry
        timeout = httpx.Timeout(30.0, connect=20.0)
        http_client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )
        
        # Create request instance
        request = HTTPXRequest(
            client=http_client,
            read_timeout=30,
            write_timeout=30,
            connect_timeout=20,
            pool_timeout=20
        )
        
        # Create application
        application = Application.builder() \
            .token(TOKEN) \
            .request(request) \
            .connect_timeout(30.0) \
            .read_timeout(30.0) \
            .write_timeout(30.0) \
            .build()
        
        # Add command handlers
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("help", help))
        application.add_handler(CommandHandler("add", add_anniversary))
        application.add_handler(CommandHandler("list", list_anniversaries))
        application.add_handler(CommandHandler("remove", remove_anniversary))
        application.add_handler(CommandHandler("today", today_anniversaries))
        application.add_handler(CommandHandler("upcoming", upcoming_anniversaries))
        application.add_handler(CommandHandler("subscribe", subscribe))
        application.add_handler(CommandHandler("unsubscribe", unsubscribe))
        application.add_handler(CommandHandler("stats", stats))
        
        # Handle text input for /add
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_input))
        
        # Error handler
        application.add_error_handler(error_handler)
        
        # Schedule daily reminders at 9:00 AM
        job_queue = application.job_queue
        if job_queue:
            job_queue.run_daily(
                send_daily_reminders,
                time=datetime.strptime("09:00", "%H:%M").time(),
                name="daily_reminder"
            )
            logger.info("✅ Daily reminder scheduled for 9:00 AM")
        
        # Start the bot
        logger.info("🚀 Starting bot...")
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            poll_interval=1.0,
            timeout=30
        )
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        raise

if __name__ == "__main__":
    main()
