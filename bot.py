import os
import re
import zipfile
import time
import asyncio
import logging
from dotenv import load_dotenv
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from mega import Mega


load_dotenv()


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


BOT_TOKEN = os.getenv("BOT_TOKEN")
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")


app = Client("MegaDownloadBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


mega = Mega()
try:
    mega_client = mega.login()
    logger.info("✅ Logged into Mega.nz successfully")
except Exception as e:
    logger.error(f"❌ Failed to log into Mega.nz: {e}")
    raise SystemExit


def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ℹ️ Help", callback_data="help"),
         InlineKeyboardButton("📄 About", callback_data="about")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])

@app.on_message(filters.command("start"))
async def start_cmd(client, message):
    await message.reply_text(
        "👋 **Welcome!**\n\n"
        "I'm a Mega.nz downloader bot. Just send a Mega link and I'll fetch the file for you.\n\n"
        "Use the buttons below to learn more ⬇️",
        reply_markup=main_keyboard()
    )

@app.on_callback_query(filters.regex("help"))
async def help_callback(client, cq):
    await cq.message.edit_text(
        "**🛠️ How to Use**\n\n"
        "1️⃣ Send me any valid Mega.nz file link.\n"
        "2️⃣ I'll download it and send it back here.\n"
        "3️⃣ Files over 2 GB are automatically split.\n"
        "4️⃣ ZIP files will be extracted before sending.\n\n"
        "⚠️ Folder links are not supported yet.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]])
    )

@app.on_callback_query(filters.regex("about"))
async def about_callback(client, cq):
    await cq.message.edit_text(
        "🤖 **About this bot**\n\n"
        "This bot downloads and sends Mega.nz files directly to Telegram.\n"
        "Supports files up to 2 GB per message (auto-split if larger).\n\n"
        "✨ Created by [@NT_BOT_CHANNEL](https://t.me/NT_BOT_CHANNEL)",
        disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back")]])
    )

@app.on_callback_query(filters.regex("cancel"))
async def cancel_callback(client, cq):
    await cq.message.edit_text("❌ Action cancelled. You can send a new Mega link anytime.")

@app.on_callback_query(filters.regex("back"))
async def back_callback(client, cq):
    await cq.message.edit_text(
        "👋 **Welcome back!**\n\n"
        "Send a Mega.nz file link to download it.\n\n"
        "Use buttons below for help or info:",
        reply_markup=main_keyboard()
    )

# 💋 ---------- CORE FUNCTIONS ---------- 💋 #
async def async_download(mega_client, link, dest):
    """Async wrapper for blocking Mega downloads."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: mega_client.download_url(link, dest_path=dest))

async def send_large_file(client, chat_id, file_path):
    """Handles splitting and uploading of large files."""
    chunk_size = 2 * 1024 * 1024 * 1024  # 2GB
    file_size = os.path.getsize(file_path)
    total_parts = (file_size // chunk_size) + 1

    with open(file_path, 'rb') as f:
        part_num = 1
        while chunk := f.read(chunk_size):
            chunk_path = f"{file_path}.part{part_num}"
            with open(chunk_path, 'wb') as cf:
                cf.write(chunk)
            await client.send_document(chat_id, document=chunk_path,
                                       caption=f"📦 {os.path.basename(file_path)} (Part {part_num}/{total_parts})")
            os.remove(chunk_path)
            part_num += 1

async def handle_zip_and_upload(client, chat_id, file_path):
    """Extracts ZIPs and uploads contents."""
    extract_dir = os.path.join("downloads", "unzipped")
    os.makedirs(extract_dir, exist_ok=True)

    with zipfile.ZipFile(file_path, 'r') as zf:
        zf.extractall(extract_dir)
    os.remove(file_path)

    for root, _, files in os.walk(extract_dir):
        for file in files:
            file_to_send = os.path.join(root, file)
            await client.send_document(chat_id, document=file_to_send,
                                       caption=f"🗂 Extracted: {file}")
            os.remove(file_to_send)

    os.rmdir(extract_dir)

# 🔥 ---------- MAIN DOWNLOAD HANDLER ---------- 🔥 #
@app.on_message(filters.text & filters.regex(r"https://mega\.nz/(file|folder)/[A-Za-z0-9_-]+(?:#[A-Za-z0-9_-]+)?"))
async def handle_mega_link(client, message):
    link = re.search(r"https://mega\.nz/(file|folder)/[A-Za-z0-9_-]+(?:#[A-Za-z0-9_-]+)?", message.text).group(0)

    if "folder" in link:
        await message.reply("🚫 Folder downloads are not supported right now.")
        return

    dest = "downloads"
    os.makedirs(dest, exist_ok=True)

    progress_msg = await message.reply("📥 **Downloading from Mega.nz... Please wait.**")

    try:
        start = time.time()
        file_path = await async_download(mega_client, link, dest)
        elapsed = time.time() - start

        if not os.path.exists(file_path):
            raise Exception("Download failed or file not found.")

        # Handle zip extraction
        if zipfile.is_zipfile(file_path):
            await progress_msg.edit_text("📦 Detected ZIP file, extracting...")
            await handle_zip_and_upload(client, message.chat.id, file_path)
        else:
            size = os.path.getsize(file_path)
            if size > 2 * 1024 * 1024 * 1024:
                await progress_msg.edit_text("📤 File is larger than 2 GB, splitting before upload...")
                await send_large_file(client, message.chat.id, file_path)
            else:
                await progress_msg.edit_text("📤 Uploading file...")
                await client.send_document(message.chat.id, document=file_path,
                                           caption="✅ Download complete!\n❤️ by @NT_BOT_CHANNEL")
                os.remove(file_path)

        await progress_msg.edit_text(f"✅ **Completed in {elapsed:.2f} seconds!**")
    except Exception as e:
        logger.error(f"Download error: {e}")
        await progress_msg.edit_text(f"❌ **Error:** {e}")

if __name__ == "__main__":
    logger.info("🚀 Bot started successfully!")
    app.run()
