import os
import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import json
from pathlib import Path

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
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
    if Path(DATA_FILE).exists():
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return DEFAULT_DATA.copy()

def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)

# Anniversary class for easier handling
class AnniversaryManager:
    def __init__(self):
        self.data = load_data()
        
    def add_anniversary(self, name, day, month, year=None, chat_id=None):
        """Add a new anniversary"""
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
        """Remove an anniversary by ID"""
        self.data["anniversaries"] = [a for a in self.data["anniversaries"] if a["id"] != anniv_id]
        save_data(self.data)
    
    def get_today_anniversaries(self):
        """Get all anniversaries for today"""
        today = datetime.now()
        today_annivs = []
        for anniv in self.data["anniversaries"]:
            if anniv["day"] == today.day and anniv["month"] == today.month:
                # Check if it's the exact anniversary year (if year is specified)
                if anniv["year"]:
                    if anniv["year"] == today.year:
                        today_annivs.append(anniv)
                else:
                    # If no year specified, it's a recurring anniversary
                    today_annivs.append(anniv)
        return today_annivs
    
    def get_upcoming_anniversaries(self, days_ahead=7):
        """Get anniversaries in the next X days"""
        from datetime import timedelta
        today = datetime.now()
        upcoming = []
        for anniv in self.data["anniversaries"]:
            # Create a date object for this anniversary this year
            try:
                anniv_date = datetime(today.year, anniv["month"], anniv["day"])
                if anniv_date < today:
                    anniv_date = datetime(today.year + 1, anniv["month"], anniv["day"])
                days_until = (anniv_date - today).days
                if 0 <= days_until <= days_ahead:
                    upcoming.append((anniv, days_until))
            except ValueError:
                # Handle invalid dates (e.g., Feb 30)
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
        """Add a chat to the subscriber list"""
        chat_id_str = str(chat_id)
        if chat_id_str not in self.data["subscribers"]:
            self.data["subscribers"].append(chat_id_str)
            save_data(self.data)
            return True
        return False
    
    def remove_subscriber(self, chat_id):
        """Remove a chat from the subscriber list"""
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
    """Send a welcome message when /start is issued"""
    user = update.effective_user
    await update.message.reply_text(
        f"🎉 Hello {user.first_name}!\n\n"
        "I'm **AnniversarysBot** - your personal anniversary reminder! 🎂\n\n"
        "📌 **Available Commands:**\n"
        "/add - Add a new anniversary (name, day, month, year optional)\n"
        "/list - List all saved anniversaries\n"
        "/remove - Remove an anniversary\n"
        "/today - Check anniversaries for today\n"
        "/upcoming - Check anniversaries in the next 7 days\n"
        "/subscribe - Get daily anniversary notifications\n"
        "/unsubscribe - Stop notifications\n"
        "/help - Show this message again\n\n"
        "👥 You can use this bot in groups too!\n"
        "Add me to a group and use /subscribe to start getting reminders.",
        parse_mode="Markdown"
    )

async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show help message"""
    await start(update, context)

async def add_anniversary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add a new anniversary via inline keyboard flow"""
    # Check if there are arguments
    if context.args:
        # Format: /add Name DD MM YYYY
        try:
            args = context.args
            if len(args) < 3:
                await update.message.reply_text(
                    "❌ Please provide: `/add Name DD MM YYYY`\n"
                    "Example: `/add Wedding 15 06 2022`\n"
                    "Year is optional: `/add Birthday 01 01`"
                )
                return
            
            # Parse name (could be multiple words)
            name_parts = []
            day_index = None
            month_index = None
            year_index = None
            
            # Find the day, month, year in the arguments
            for i, arg in enumerate(args):
                if arg.isdigit():
                    if int(arg) <= 31:  # Could be day
                        if day_index is None:
                            day_index = i
                        else:
                            month_index = i
                    elif int(arg) <= 9999:  # Could be year
                        year_index = i
            
            if day_index is not None and month_index is not None:
                day = int(args[day_index])
                month = int(args[month_index])
                
                # Get name (everything before the first number)
                name_parts = args[:day_index]
                name = " ".join(name_parts) if name_parts else "Anniversary"
                
                # Get year if present
                year = None
                if year_index is not None and year_index > month_index:
                    year = int(args[year_index])
                
                # Validate date
                if 1 <= day <= 31 and 1 <= month <= 12:
                    manager.add_anniversary(name, day, month, year, update.effective_chat.id)
                    
                    year_text = f" in {year}" if year else " (recurring annually)"
                    await update.message.reply_text(
                        f"✅ Added anniversary: **{name}** on {day}/{month}{year_text}!"
                    )
                    return
                else:
                    await update.message.reply_text("❌ Invalid date! Please use valid day (1-31) and month (1-12).")
                    return
            else:
                await update.message.reply_text(
                    "❌ Please provide: `/add Name DD MM YYYY`\n"
                    "Example: `/add Wedding 15 06 2022`"
                )
                return
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {str(e)}\nPlease use format: `/add Name DD MM YYYY`")
            return
    
    # If no arguments, ask for input via conversation
    context.user_data["awaiting_add"] = True
    await update.message.reply_text(
        "📝 Please send the anniversary details in this format:\n\n"
        "`Name, DD, MM, YYYY`\n"
        "Example: `Wedding, 15, 06, 2022`\n\n"
        "Or just: `Birthday, 01, 01` (year is optional)\n"
        "Send /cancel to cancel.",
        parse_mode="Markdown"
    )

async def handle_add_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the text input for adding an anniversary"""
    if not context.user_data.get("awaiting_add"):
        return
    
    text = update.message.text
    if text == "/cancel":
        context.user_data["awaiting_add"] = False
        await update.message.reply_text("❌ Cancelled adding anniversary.")
        return
    
    try:
        # Parse: Name, DD, MM, YYYY
        parts = [p.strip() for p in text.split(",")]
        if len(parts) < 3 or len(parts) > 4:
            await update.message.reply_text(
                "❌ Please use: `Name, DD, MM, YYYY`\n"
                "Example: `Wedding, 15, 06, 2022`"
            )
            return
        
        name = parts[0]
        day = int(parts[1])
        month = int(parts[2])
        year = int(parts[3]) if len(parts) == 4 else None
        
        if 1 <= day <= 31 and 1 <= month <= 12:
            manager.add_anniversary(name, day, month, year, update.effective_chat.id)
            year_text = f" in {year}" if year else " (recurring annually)"
            await update.message.reply_text(
                f"✅ Added anniversary: **{name}** on {day}/{month}{year_text}!"
            )
            context.user_data["awaiting_add"] = False
        else:
            await update.message.reply_text("❌ Invalid date! Please use valid day (1-31) and month (1-12).")
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid format! Please use: `Name, DD, MM, YYYY`\n"
            "Example: `Wedding, 15, 06, 2022`"
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def list_anniversaries(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all saved anniversaries"""
    anniversaries = manager.get_all_anniversaries()
    chat_id = str(update.effective_chat.id)
    
    # Filter for this chat
    chat_annivs = [a for a in anniversaries if a.get("chat_id") == chat_id or a.get("chat_id") is None]
    
    if not chat_annivs:
        await update.message.reply_text(
            "📭 No anniversaries saved yet!\n"
            "Use /add to add one."
        )
        return
    
    # Create a nice list
    message = "📋 **Your Anniversaries:**\n\n"
    for anniv in chat_annivs:
        year_text = f" ({anniv['year']})" if anniv.get("year") else " (recurring)"
        message += f"🆔 {anniv['id']}: **{anniv['name']}** - {anniv['day']}/{anniv['month']}{year_text}\n"
    
    message += "\n📌 Use `/remove ID` to delete an anniversary."
    await update.message.reply_text(message, parse_mode="Markdown")

async def remove_anniversary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove an anniversary by ID"""
    if not context.args:
        await update.message.reply_text("❌ Please provide the anniversary ID: `/remove 1`")
        return
    
    try:
        anniv_id = int(context.args[0])
        anniv = manager.get_anniversary_by_id(anniv_id)
        
        if anniv:
            # Check if this chat owns the anniversary
            chat_id = str(update.effective_chat.id)
            if anniv.get("chat_id") and anniv["chat_id"] != chat_id:
                await update.message.reply_text("❌ This anniversary was added by another chat.")
                return
            
            manager.remove_anniversary(anniv_id)
            await update.message.reply_text(f"✅ Removed anniversary: **{anniv['name']}**")
        else:
            await update.message.reply_text("❌ Anniversary not found. Use /list to see all IDs.")
    except ValueError:
        await update.message.reply_text("❌ Please provide a valid number: `/remove 1`")

async def today_anniversaries(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check anniversaries for today"""
    today_annivs = manager.get_today_anniversaries()
    chat_id = str(update.effective_chat.id)
    
    # Filter for this chat
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
    """Show anniversaries in the next 7 days"""
    days_ahead = 7
    if context.args:
        try:
            days_ahead = int(context.args[0])
        except ValueError:
            days_ahead = 7
    
    upcoming = manager.get_upcoming_anniversaries(days_ahead)
    chat_id = str(update.effective_chat.id)
    
    # Filter for this chat
    chat_upcoming = [(a, d) for a, d in upcoming if a.get("chat_id") == chat_id or a.get("chat_id") is None]
    
    if not chat_upcoming:
        await update.message.reply_text(f"📅 No anniversaries in the next {days_ahead} days!")
        return
    
    message = f"📅 **Upcoming Anniversaries ({days_ahead} days):**\n\n"
    for anniv, days in chat_upcoming:
        year_text = f" ({anniv['year']})" if anniv.get("year") else ""
        if days == 0:
            day_text = "**🎉 TODAY!**"
        elif days == 1:
            day_text = "Tomorrow"
        else:
            day_text = f"In {days} days"
        message += f"• **{anniv['name']}** - {day_text} ({anniv['day']}/{anniv['month']}{year_text})\n"
    
    await update.message.reply_text(message, parse_mode="Markdown")

async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Subscribe to daily anniversary notifications"""
    chat_id = update.effective_chat.id
    if manager.add_subscriber(chat_id):
        await update.message.reply_text(
            "✅ **Subscribed!** 🎉\n\n"
            "I'll send you daily anniversary notifications at 9:00 AM."
        )
    else:
        await update.message.reply_text("ℹ️ You're already subscribed!")

async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unsubscribe from daily notifications"""
    chat_id = update.effective_chat.id
    if manager.remove_subscriber(chat_id):
        await update.message.reply_text("✅ Unsubscribed from daily notifications.")
    else:
        await update.message.reply_text("ℹ️ You weren't subscribed.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot statistics"""
    anniversaries = manager.get_all_anniversaries()
    subscribers = manager.get_subscribers()
    
    message = f"📊 **Bot Statistics:**\n\n"
    message += f"📝 Total anniversaries: {len(anniversaries)}\n"
    message += f"👥 Subscribers: {len(subscribers)}\n"
    message += f"⏰ Daily notifications at: 9:00 AM"
    
    await update.message.reply_text(message, parse_mode="Markdown")

# ----- DAILY REMINDER FUNCTION -----

async def send_daily_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Send daily anniversary reminders to all subscribers"""
    today_annivs = manager.get_today_anniversaries()
    if not today_annivs:
        return
    
    subscribers = manager.get_subscribers()
    
    # Group anniversaries by chat_id
    for chat_id in subscribers:
        try:
            # Filter anniversaries for this chat
            chat_annivs = [a for a in today_annivs if a.get("chat_id") == chat_id or a.get("chat_id") is None]
            
            if chat_annivs:
                message = "🌅 **Good Morning! Today's Anniversaries:** 🎉\n\n"
                for anniv in chat_annivs:
                    year_text = f" ({anniv['year']})" if anniv.get("year") else ""
                    message += f"🎂 **{anniv['name']}** - {anniv['day']}/{anniv['month']}{year_text}\n"
                message += "\n🎊 Celebrate and make it special!"
                
                await context.bot.send_message(chat_id=int(chat_id), text=message, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Failed to send reminder to {chat_id}: {e}")

# ----- MAIN FUNCTION -----

def main():
    """Start the bot"""
    # Create the Application
    application = Application.builder().token(TOKEN).build()
    
    # Command handlers
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
    
    # Handle text input for /add command
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_add_input))
    
    # Schedule daily reminders at 9:00 AM
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_daily(
            send_daily_reminders,
            time=datetime.strptime("09:00", "%H:%M").time(),
            name="daily_reminder"
        )
        logger.info("Daily reminder scheduled for 9:00 AM")
    
    # Start the bot
    logger.info("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
