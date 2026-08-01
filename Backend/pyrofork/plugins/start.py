from asyncio import create_task, sleep as asleep
from urllib.parse import urlparse
from Backend.logger import LOGGER
from Backend import db
from Backend.config import Telegram
from Backend.helper.custom_filter import CustomFilters
from Backend.helper.appwrite_admin import AppwriteAdmin, describe_appwrite_error, format_expiry_time, format_remaining_duration
from Backend.helper.encrypt import decode_string
from Backend.helper.metadata import metadata
from Backend.helper.pyro import clean_filename, get_readable_file_size, remove_urls
from Backend.pyrofork import StreamBot
from pyrogram import filters, Client
from pyrogram.types import Message
from os import path as ospath
from pyrogram.errors import FloodWait
from pyrogram.enums.parse_mode import ParseMode
from themoviedb import aioTMDb
from asyncio import Queue, create_task, to_thread
from os import execl as osexecl
from asyncio import create_subprocess_exec, gather
from sys import executable
from aiofiles import open as aiopen
from pyrogram import enums


tmdb = aioTMDb(key=Telegram.TMDB_API, language="en-US", region="US")
# Initialize database connection
import random
import string
from passlib.context import CryptContext
from datetime import datetime, timedelta

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

def generate_password(length=10):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def stremio_manifest_url(token: str) -> str:
    base_url = Telegram.BASE_URL
    if not base_url or base_url in ("0.0.0.0", "127.0.0.1", "localhost"):
        return f"/stremio/{token}/manifest.json"
    return f"{base_url.rstrip('/')}/stremio/{token}/manifest.json"

@StreamBot.on_message(filters.command("help") & filters.private & CustomFilters.owner)
async def owner_help(bot: Client, message: Message):
    await message.reply_text(
        "**X-Stream Owner Commands**\n\n"
        "**Premium members**\n"
        "`/premium <email> <duration|date>` - create/update premium access\n"
        "`/pinfo <email>` - show user, subscription, remaining time, and Stremio/Nuvio link\n"
        "`/pdelete <email>` - delete Appwrite user, subscription rows, and watchlist rows\n\n"
        "**Duration examples**\n"
        "`30m`, `10 minutes`, `12h`, `7d`, `2026-12-31`\n\n"
        "**Backend controls**\n"
        "`/restart` - restart backend\n"
        "`/log` - send backend log file\n"
        "`/caption` - toggle caption parsing\n"
        "`/tmdb` - toggle TMDB/IMDB metadata\n"
        "`/set <url>` - set default URL, or `/set` to remove it\n\n"
        "**Trending**\n"
        "`/pin [slot] <media>` - pin media to trending\n"
        "`/unpin <slot>` - remove a trending slot\n"
        "`/move <from> <to>` - move a trending item\n"
        "`/trending` - list trending slots\n"
        "`/delete <mov|ser> <tmdb_id>` - delete media from database\n\n"
        "**Legacy local auth**\n"
        "`/user <username> <expiry_days>` - create old Mongo auth user",
        parse_mode=ParseMode.MARKDOWN,
    )

@StreamBot.on_message(filters.command("user") & filters.private & CustomFilters.owner)
async def create_user(bot: Client, message: Message):
    try:
        args = message.text.split()
        if len(args) != 3:
            await message.reply_text("❌ Usage: `/user <username> <expiry_days>`", parse_mode=ParseMode.MARKDOWN)
            return

        username = args[1]
        expiry_days = int(args[2])

        users_collection = db.db["auth_users"]  # Use the Tracking database

        # Check if username already exists
        existing_user = await users_collection.find_one({"username": username})
        if existing_user:
            await message.reply_text(f"❌ User `{username}` already exists!", parse_mode=ParseMode.MARKDOWN)
            return

        password = generate_password()
        hashed_password = pwd_ctx.hash(password)
        expires_at = datetime.utcnow() + timedelta(days=expiry_days)

        user_data = {
            "username": username,
            "password": hashed_password,
            "expires_at": expires_at
        }
        await users_collection.insert_one(user_data)

        await message.reply_text(
            f"✅ User created!\n\n"
            f"👤 Username: `{username}`\n"
            f"🔑 Password: `{password}`\n"
            f"🕒 Expires in: `{expiry_days}` days\n"
            f"📅 Expiry Date: `{expires_at.strftime('%Y-%m-%d %H:%M:%S')} UTC`",
            parse_mode=ParseMode.MARKDOWN
        )

    except Exception as e:
        LOGGER.error(f"Error in /user command: {e}")
        await message.reply_text("❌ An error occurred while creating the user.")

@StreamBot.on_message(filters.command("premium") & filters.private & CustomFilters.owner)
async def grant_premium(bot: Client, message: Message):
    try:
        args = message.text.split()
        if len(args) < 3:
            await message.reply_text(
                "❌ Usage: `/premium <email> <duration|date>`\n\n"
                "Examples:\n"
                "`/premium user@example.com 30m`\n"
                "`/premium user@example.com 10 minutes`\n"
                "`/premium user@example.com 12h`\n"
                "`/premium user@example.com 7d`\n"
                "`/premium user@example.com 2026-12-31`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        admin = AppwriteAdmin()
        result = await to_thread(admin.grant_premium, args[1], " ".join(args[2:]))
        stremio_token = await to_thread(admin.create_stremio_token, result.user)
        expiry_utc = format_expiry_time(result.row.get("expiryDate"), "UTC")
        expiry_ist = format_expiry_time(result.row.get("expiryDate"), "IST")
        response = (
            "✅ Premium access updated successfully!\n\n"
            f"📧 Email: `{result.user['email']}`\n"
            f"👤 User ID: `{result.user['$id']}`\n"
            f"🟢 Subscription: `active`\n"
            f"🔐 isActive: `true`\n"
            f"📅 Expires (IST): `{expiry_ist}`\n"
            f"🌐 Expires (UTC): `{expiry_utc}`\n"
            f"🕒 Time remaining: `{format_remaining_duration(result.row.get('expiryDate'))}`\n"
            f"📺 Stremio/Nuvio: `{stremio_manifest_url(stremio_token)}`"
        )
        if result.created_user and result.created_password:
            response += f"\n🔑 Temporary Password: `{result.created_password}`"
        elif result.reactivated_user:
            response += "\n🔓 Existing Appwrite account was reactivated."

        await message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        LOGGER.error(f"Error in /premium command: {e}")
        await message.reply_text(f"❌ {describe_appwrite_error(e)}")

@StreamBot.on_message(filters.command("pdelete") & filters.private & CustomFilters.owner)
async def delete_premium_member(bot: Client, message: Message):
    try:
        args = message.text.split()
        if len(args) != 2:
            await message.reply_text("❌ Usage: `/pdelete <email>`", parse_mode=ParseMode.MARKDOWN)
            return

        admin = AppwriteAdmin()
        result = await to_thread(admin.delete_member, args[1])
        user_status = "deleted" if result.deleted_user else "not found"
        await message.reply_text(
            "✅ Member cleanup complete!\n\n"
            f"📧 Email: `{result.email}`\n"
            f"👤 Auth user: `{user_status}`\n"
            f"🧾 Subscription rows deleted: `{result.deleted_subscriptions}`\n"
            f"⭐ Watchlist rows deleted: `{result.deleted_watchlist_items}`",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        LOGGER.error(f"Error in /pdelete command: {e}")
        await message.reply_text(f"❌ {describe_appwrite_error(e)}")

@StreamBot.on_message(filters.command("pinfo") & filters.private & CustomFilters.owner)
async def premium_member_info(bot: Client, message: Message):
    try:
        args = message.text.split()
        if len(args) != 2:
            await message.reply_text("❌ Usage: `/pinfo <email>`", parse_mode=ParseMode.MARKDOWN)
            return

        admin = AppwriteAdmin()
        info = await to_thread(admin.get_member_info, args[1])

        if not info.user and not info.subscriptions:
            await message.reply_text(f"❌ No Appwrite user or subscription found for `{info.email}`.", parse_mode=ParseMode.MARKDOWN)
            return

        lines = [
            "ℹ️ Premium member info",
            "",
            f"📧 Email: `{info.email}`",
            f"👤 Auth user: `{'found' if info.user else 'not found'}`",
        ]

        if info.user:
            lines.extend([
                f"🆔 User ID: `{info.user.get('$id')}`",
                f"✅ User enabled/status: `{info.user.get('status')}`",
                f"✉️ Email verified: `{info.user.get('emailVerification')}`",
                f"📅 Created: `{info.user.get('$createdAt')}`",
                f"🕒 Updated: `{info.user.get('$updatedAt')}`",
            ])
            if info.stremio_token:
                lines.append(f"📺 Stremio/Nuvio: `{stremio_manifest_url(info.stremio_token)}`")

        lines.append(f"⭐ Watchlist rows: `{info.watchlist_count}`")
        lines.append(f"🧾 Subscription rows: `{len(info.subscriptions)}`")

        for index, row in enumerate(info.subscriptions, start=1):
            lines.extend([
                "",
                f"Subscription #{index}",
                f"• Row ID: `{row.get('$id')}`",
                f"• Type: `{row.get('subscriptionType')}`",
                f"• Status: `{row.get('subscriptionStatus')}`",
                f"• isActive: `{row.get('isActive')}`",
                f"• Start (IST): `{format_expiry_time(row.get('startDate'), 'IST')}`",
                f"• Expiry (IST): `{format_expiry_time(row.get('expiryDate'), 'IST')}`",
                f"• Expiry (UTC): `{format_expiry_time(row.get('expiryDate'), 'UTC')}`",
                f"• Remaining: `{format_remaining_duration(row.get('expiryDate'))}`",
                f"• Updated: `{row.get('updatedAt')}`",
            ])

        await message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        LOGGER.error(f"Error in /pinfo command: {e}")
        await message.reply_text(f"❌ {describe_appwrite_error(e)}")

@StreamBot.on_message(filters.command('restart') & filters.private & CustomFilters.owner)
async def restart(bot: Client, message: Message):
    try:
        # Notify the user that the bot is restarting

        restart_message = await message.reply_text(
    '<blockquote>⚙️ Restarting Backend API... \n\n✨ Please wait as we bring everything back online! 🚀</blockquote>',
        quote=True,
        parse_mode=enums.ParseMode.HTML
        )
        LOGGER.info("Restart initiated by owner.")

        # Run the update script
        proc1 = await create_subprocess_exec('python3', 'update.py')
        await gather(proc1.wait())

        # Save restart message details for notification after restart
        async with aiopen(".restartmsg", "w") as f:
            await f.write(f"{restart_message.chat.id}\n{restart_message.id}\n")

        # Restart the bot process
        osexecl(executable, executable, "-m", "Backend")

    except Exception as e:
        LOGGER.error(f"Error during restart: {e}")
        await message.reply_text("**❌ Failed to restart. Check logs for details.**")




async def delete_messages_after_delay(messages):
    await asleep(300)
    for msg in messages:
        try:
            await msg.delete()
        except Exception as e:
            LOGGER.error(f"Error deleting message {msg.id}: {e}")
        await asleep(2)

@StreamBot.on_message(filters.command('start') & filters.private)
async def start(bot: Client, message: Message):
    LOGGER.info(f"Received command: {message.text}")

    command_part = message.text.split('start ')[-1]

    if command_part.startswith("file_"):
        usr_cmd = command_part[len("file_"):].strip()

        parts = usr_cmd.split("_")

        if len(parts) == 2:
            try:
                tmdb_id, quality = parts
                tmdb_id = int(tmdb_id)
                season = None
                quality_details = await db.get_quality_details(tmdb_id, quality)
            except ValueError:
                LOGGER.error(f"Error parsing movie command: {usr_cmd}")
                await message.reply_text("Invalid command format for movie.")
                return

        elif len(parts) == 3:
            try:
                tmdb_id, season, quality = parts
                tmdb_id = int(tmdb_id)
                season = int(season)
                quality_details = await db.get_quality_details(tmdb_id, quality, season)
            except ValueError:
                LOGGER.error(f"Error parsing TV show command: {usr_cmd}")
                await message.reply_text("Invalid command format for TV show.")
                return
        elif len(parts) == 4:
            try:
                tmdb_id, season, episode, quality = parts
                tmdb_id = int(tmdb_id)
                season = int(season)
                episode = int(episode)
                quality_details = await db.get_quality_details(tmdb_id, quality, season, episode)
            except ValueError:
                LOGGER.error(f"Error parsing TV show command: {usr_cmd}")
                await message.reply_text("Invalid command format for TV show.")
                return

        else:
            await message.reply_text("Invalid command format.")
            return

        sent_messages = []
        for detail in quality_details:
            decoded_data = await decode_string(detail['id'])
            channel = f"-100{decoded_data['chat_id']}"
            msg_id = decoded_data['msg_id']
            name = detail['name']
            if "\\n" in name and name.endswith(".mkv"):
                name = name.rsplit(".mkv", 1)[0].replace("\\n", "\n")
            try:
                file = await bot.get_messages(int(channel), int(msg_id))
                media = file.document or file.video
                if media:
                    sent_msg = await message.reply_cached_media(
                        file_id=media.file_id,
                        caption=f'{name}'
                    )
                    sent_messages.append(sent_msg)
                    await asleep(1)
            except FloodWait as e:
                LOGGER.info(f"Sleeping for {e.value}s")
                await asleep(e.value)
                await message.reply_text(f"Got Floodwait of {e.value}s")
            except Exception as e:
                LOGGER.error(f"Error retrieving/sending media: {e}")
                await message.reply_text("Error retrieving media.")

        if sent_messages:
            warning_msg = await message.reply_text(
                "Forward these files to your saved messages. These files will be deleted from the bot within 5 minutes."
            )
            sent_messages.append(warning_msg)
            create_task(delete_messages_after_delay(sent_messages))
    else:
        await message.reply_text("Hello 👋")



@StreamBot.on_message(filters.command('log') & filters.private & CustomFilters.owner)
async def start(bot: Client, message: Message):
    try:
        path = ospath.abspath('log.txt')
        return await message.reply_document(
        document=path, quote=True, disable_notification=True
        )
    except Exception as e:
        print(f"An error occurred: {e}")




# Global queue for processing file updates
from asyncio import Lock

file_queue = Queue()
db_lock = Lock()

async def process_file():
    while True:
        metadata_info, hash, channel, msg_id, size, title = await file_queue.get()
        try:
            async with db_lock:
                LOGGER.info(
                    "Processing queued %s file: channel=%s message=%s title=%s",
                    metadata_info.get("media_type"),
                    channel,
                    msg_id,
                    title,
                )
                updated_id = await db.insert_media(
                    metadata_info,
                    hash=hash,
                    channel=channel,
                    msg_id=msg_id,
                    size=size,
                    name=title,
                )
                if updated_id:
                    LOGGER.info(f"{metadata_info['media_type']} updated with ID: {updated_id}")
                else:
                    LOGGER.info("Update failed due to validation errors.")
        except Exception:
            LOGGER.exception(
                "Failed to process queued file: channel=%s message=%s title=%s metadata=%r",
                channel,
                msg_id,
                title,
                metadata_info,
            )
        finally:
            file_queue.task_done()

for _ in range(1):
    create_task(process_file())


@StreamBot.on_message(filters.channel & (filters.document | filters.video))
async def file_receive_handler(bot: Client, message: Message):
    if str(message.chat.id) in Telegram.AUTH_CHANNEL:
        try:
            if message.video or message.document.mime_type.startswith("video/"):
                file = message.video or message.document
                if message.caption:
                    title = message.caption.replace("\n", "\\n")
                else:
                    title = file.file_name or file.file_id

                msg_id = message.id
                hash = file.file_unique_id[:6]
                size = get_readable_file_size(file.file_size)
                channel = str(message.chat.id).replace("-100", "")

                cleaned_title = clean_filename(title)
                LOGGER.info(
                    "Received media file: channel=%s message=%s filename=%s cleaned=%s",
                    message.chat.id,
                    msg_id,
                    title,
                    cleaned_title,
                )
                metadata_info = await metadata(cleaned_title, file)
                if metadata_info is None:
                    LOGGER.warning(
                        "Metadata parsing returned no result: channel=%s message=%s filename=%s",
                        message.chat.id,
                        msg_id,
                        title,
                    )
                    return await message.reply_text("> Not added check log")
                title = remove_urls(title)
                if not title.endswith(('.mkv', '.mp4')):
                    title += '.mkv'
                await file_queue.put((metadata_info, hash, int(channel), msg_id, size, title))
                LOGGER.info(
                    "Queued %s file: channel=%s message=%s title=%s",
                    metadata_info.get("media_type"),
                    message.chat.id,
                    msg_id,
                    title,
                )
            else:
                await message.reply_text("> Not supported")
        except FloodWait as e:
            LOGGER.info(f"Sleeping for {str(e.value)}s")
            await asleep(e.value)
            await message.reply_text(text=f"Got Floodwait of {str(e.value)}s",
                                disable_web_page_preview=True, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            LOGGER.exception(
                "Unhandled error receiving media: channel=%s message=%s",
                message.chat.id,
                message.id,
            )
            await message.reply_text("> Not added check log")
    else:
        await message.reply(text="> Channel is not in AUTH_CHANNEL")


@Client.on_message(filters.command('caption') & filters.private & CustomFilters.owner)
async def toggle_caption(bot: Client, message: Message):
    try:
        Telegram.USE_CAPTION = not Telegram.USE_CAPTION
        await message.reply_text(f"Now Bot Uses {'Caption' if Telegram.USE_CAPTION else 'Filename'}")
    except Exception as e:
        print(f"An error occurred: {e}")

@Client.on_message(filters.command('tmdb') & filters.private & CustomFilters.owner)
async def toggle_tmdb(bot: Client, message: Message):
    try:
        Telegram.USE_TMDB = not Telegram.USE_TMDB
        await message.reply_text(f"Now Bot Uses {'TMDB' if Telegram.USE_TMDB else 'IMDB'}")
    except Exception as e:
        print(f"An error occurred: {e}")

@Client.on_message(filters.command('set') & filters.private & CustomFilters.owner)
async def set_id(bot: Client, message: Message):

    url_part = message.text.split()[1:]  # Skip the command itself

    try:
        if len(url_part) == 1:

            Telegram.USE_DEFAULT_ID = url_part[0]  # Get the first element
            await message.reply_text(f"Now Bot Uses Default URL: {Telegram.USE_DEFAULT_ID}")
        else:
            # Remove the default ID
            Telegram.USE_DEFAULT_ID = None
            await message.reply_text("Removed default ID.")
    except Exception as e:
        await message.reply_text(f"An error occurred: {e}")


def parse_media_reference(parts):
    slot = None
    tokens = list(parts)

    if tokens and tokens[0].isdigit() and 1 <= int(tokens[0]) <= 10:
        slot = int(tokens.pop(0))

    if not tokens:
        return slot, None, None

    first = tokens[0]
    parsed_url = urlparse(first)
    path_parts = [part for part in parsed_url.path.split("/") if part]
    if parsed_url.scheme and len(path_parts) >= 2 and path_parts[-2] in ("mov", "ser") and path_parts[-1].isdigit():
        media_type = "movie" if path_parts[-2] == "mov" else "tv"
        return slot, media_type, int(path_parts[-1])

    if first in ("mov", "movie", "ser", "tv", "tvshow") and len(tokens) >= 2 and tokens[1].isdigit():
        media_type = "movie" if first in ("mov", "movie") else "tv"
        return slot, media_type, int(tokens[1])

    if first.isdigit():
        return slot, "movie", int(first)

    return slot, None, None


@Client.on_message(filters.command('pin') & filters.private & CustomFilters.owner)
async def pin_trending(bot: Client, message: Message):
    try:
        parts = message.text.split()[1:]
        slot, media_type, tmdb_id = parse_media_reference(parts)
        if not media_type or not tmdb_id:
            return await message.reply_text(
                "Use: /pin [slot] https://site/mov/123 or /pin [slot] mov 123 or /pin [slot] ser 123"
            )

        result = await db.pin_trending(media_type, tmdb_id, slot)
        media = result["media"]
        await message.reply_text(
            f"Pinned slot {result['slot']}: {media['title']} ({media['media_type']})"
        )
    except Exception as e:
        await message.reply_text(f"An error occurred: {str(e)}")


@Client.on_message(filters.command('unpin') & filters.private & CustomFilters.owner)
async def unpin_trending(bot: Client, message: Message):
    try:
        parts = message.text.split()
        if len(parts) != 2 or not parts[1].isdigit():
            return await message.reply_text("Use: /unpin 3")

        slot = int(parts[1])
        removed = await db.unpin_trending(slot)
        if removed:
            await message.reply_text(f"Removed trending slot {slot}.")
        else:
            await message.reply_text(f"Slot {slot} is already empty.")
    except Exception as e:
        await message.reply_text(f"An error occurred: {str(e)}")


@Client.on_message(filters.command('move') & filters.private & CustomFilters.owner)
async def move_trending(bot: Client, message: Message):
    try:
        parts = message.text.split()
        if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
            return await message.reply_text("Use: /move 2 5")

        moved = await db.move_trending(int(parts[1]), int(parts[2]))
        if moved:
            await message.reply_text(f"Moved trending slot {parts[1]} to {parts[2]}.")
        else:
            await message.reply_text(f"Slot {parts[1]} is empty.")
    except Exception as e:
        await message.reply_text(f"An error occurred: {str(e)}")


@Client.on_message(filters.command('trending') & filters.private & CustomFilters.owner)
async def list_trending(bot: Client, message: Message):
    try:
        data = await db.get_trending()
        if not data["results"]:
            return await message.reply_text("Trending is empty. Use /pin [slot] mov 123 or /pin [slot] ser 123.")

        lines = ["Trending slots:"]
        for item in data["results"]:
            media_type = "Movie" if item["media_type"] == "movie" else "Series"
            lines.append(f"{item['trending_slot']}. {item['title']} - {media_type} - {item['tmdb_id']}")
        await message.reply_text("\n".join(lines))
    except Exception as e:
        await message.reply_text(f"An error occurred: {str(e)}")





@Client.on_message(filters.command('delete') & filters.private & CustomFilters.owner)
async def delete(bot: Client, message: Message):
    try:
        split_text = message.text.split()
        if len(split_text) != 2:
            return await message.reply_text("Use this format: /delete https://domain/ser/3123")

        url = split_text[1]
        parsed_url = urlparse(url)
        path_parts = parsed_url.path.split('/')

        if len(path_parts) >= 3 and path_parts[-2] in ('ser', 'mov') and path_parts[-1].isdigit():
            media_type = path_parts[-2]
            tmdb_id = path_parts[-1]
            delete = await db.delete_document(media_type, int(tmdb_id))
            if delete:
                return await message.reply_text(f"{media_type} with ID {tmdb_id} has been deleted successfully.")
            else:
                return await message.reply_text(f"ID {tmdb_id} wasn't found in the database.")
        else:
            return await message.reply_text("The URL format is incorrect.")

    except Exception as e:
        await message.reply_text(f"An error occurred: {str(e)}")
