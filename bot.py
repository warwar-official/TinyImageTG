import asyncio
import io
import logging
import math
import os

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import FSInputFile
from datetime import datetime
from dotenv import load_dotenv
from PIL import Image

from store import AuthStore
from pipeline import pipeline_worker

# CONSTANTS

STATE_PATH = "data/state/auth.json"
LOADED_IMAGE_DIR = "data/images/loaded"
MAX_IMAGES = 3

load_dotenv()

logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TELEGRAM_TOKEN:
    raise ValueError("TELEGRAM_TOKEN is not set in environment variables or config.")
else:
    bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher()
auth_store = AuthStore('data/state/auth.json')
typing_queue = asyncio.Queue()
pipeline_queue = asyncio.Queue()

async def main() -> None:
    # Run keep typing
    try:
        asyncio.create_task(_keep_typing())
    except Exception as e:
        logger.exception("Keep typing start failed: %s", e)
    
    # Run pipeline worker
    try:
        asyncio.create_task(pipeline_worker(pipeline_queue, _answer_callback))
    except Exception as e:
        logger.exception("Pipeline worker start failed: %s", e)
    
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(e)
    finally:
        await bot.session.close()

async def send_file(chat_id: int, file_path: str, real_name: str):
    try:
        f = FSInputFile(file_path, filename=real_name)
        await bot.send_document(chat_id, f)
    except Exception as e:
        logger.exception("Failed to send file %s to chat %d: %s", file_path, chat_id, e)

# Typing indicator while processing
async def _keep_typing(interval: float = 4.0):
    user_ids = []
    while True:
        try:
            try:
                command = typing_queue.get_nowait()
                id = command.get('chat_id', None)
                action = command.get('action', None)
                if id and action:
                    if action == "start":
                        user_ids.append(id)
                    elif action == "stop":
                        try:
                            user_ids.remove(id)
                        except:
                            pass
                    else:
                        logger.exception("Unknown keep_typing action: %s", action)
                else:
                    logger.exception("Unknown keep_typing command: %s", command)
            except asyncio.QueueEmpty:
                pass
            try:
                for cid in user_ids:
                    await bot.send_chat_action(cid, "typing")
            except Exception as e:
                logger.exception("Failed to send chat action. Exception: %s", e)
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            return

async def _answer_callback(chat_id: int, resp: dict):
    await typing_queue.put({"chat_id":chat_id,"action":"stop"})
    if not resp:
        await bot.send_message(chat_id, "Empty response from bot")
        return

    if resp.get('error'):
        await bot.send_message(chat_id, f"Error: {resp.get('error')}")
        return

    if resp.get('message'):
        message_text = resp.get('message')
        await bot.send_message(chat_id, message_text)
        return
    
    if resp.get('image'):
        file = resp.get('image')
        await send_file(chat_id, file['path'], file['real_name'])
        return
    
    await bot.send_message(chat_id, f"Unexpected server responce.")
    logger.exception("Not empty, not error, not assistant respoinse found: %s", resp)

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    # track start attempts and possible bans
    auth_store.add_start_attempt(user_id)
    if auth_store.is_start_banned(user_id):
        await message.answer("You are temporarily banned from starting the bot due to repeated attempts. Try later.")
        return

    # log code generation (robust lookup of user display name)
    nickname = (
        getattr(message.from_user, 'username', None)
        or getattr(message.from_user, 'full_name', None)
        or getattr(message.from_user, 'first_name', None)
        or str(getattr(message.from_user, 'id', 'Unknown'))
    )
    logger.info(f"User {user_id} (@{nickname}) started the bot.")
    await message.answer("Welcome to TinyImage. Send your authorization code to proceed.")

@dp.message()
async def handle_all(message: types.Message):
    user_id = message.from_user.id
    auth_responce = auth_store.is_authorized(user_id)

    if not auth_responce["authorized"]:
        if auth_store.is_code_banned(user_id):
            await message.reply("You are temporarily banned from requesting codes due to repeated failures.")
            return
        if auth_responce["message"] == "Unknown type":
            await message.reply("Internal authorization error. Please contact the administrator.")
            return 
        try:
            txt = message.text.strip() if message.text else None
            if not txt:
                await message.reply("Please send your authorization code.")
                return
            # search for key
            res = auth_store.redeem_key(user_id, txt)
            # it is key
            if isinstance(res, dict) and res.get('ok'):
                # Granted via key
                ktype = res.get('type')
                if ktype == 'infinity':
                    await message.reply("Authorization complete. You have been granted infinite access.")
                elif ktype == 'user':
                    exp = res.get('expires_at', 0) or 0
                    if exp:
                        exp_str = datetime.fromtimestamp(exp).strftime('%Y-%m-%d %H:%M:%S')
                        await message.reply(f"Authorization complete. Access expires at {exp_str}.")
                    else:
                        await message.reply("Authorization complete. Access granted.")
                else:
                    logger.warning("Unknown key type '%s' for user %d", ktype, user_id)
                    await message.reply("Authorization complete. Access granted.")
                return
            # it is not key
            else:
                if isinstance(res, dict) and res.get('reason') and res.get('reason') != 'not_found':
                    # Inform user on explicit key failure (expired/used)
                    reason = res.get('reason')
                    if reason == 'expired':
                        await message.reply("This key has expired.")
                        return
                    elif reason == 'used_up':
                        await message.reply("This key has already been used the maximum number of times.")
                        return
                else:
                    if auth_responce["message"] == "Expired":
                        await message.reply("Your authorization has expired. Please contact the support to renew it.")
                        return
                    elif auth_responce["message"] == "No Access":
                        await message.reply("Send the auth code from the admin to get access.")
                        return
                    else:
                        await message.reply("Unknown authorization error. Please contact the support.")
                        return
        except Exception as e:
            # redemption errors should not block normal code auth flow
            logger.exception("Failed to redeem authorization key. Exception: %s", e)
            await message.reply("An error occurred while redeeming the key. Please try again or contact support.")
            return

        await message.reply("Please run /start and authorize first.")
        return
    
    try:
        rate = auth_store.record_message(user_id)
        if rate.get('banned'):
            # delete incoming message and notify user
            try:
                await bot.delete_message(message.chat.id, message.message_id)
            except Exception as e:
                logger.exception("Failed to delete processing message. Exception: %s", e)
            bans = auth_store.get_bans(user_id)
            ban_until = bans.get('message_ban_until', 0)
            if ban_until:
                ban_until_str = datetime.fromtimestamp(ban_until).strftime('%Y-%m-%d %H:%M:%S')
            else:
                ban_until_str = "a while"
            await bot.send_message(user_id, f"You are temporarily banned for spamming until {ban_until_str}.")
            
            return
    except Exception as e:
        logger.exception("Failed to handle rate limiting. Exception: %s", e)

    # Unknown command handling: do not forward to model
    if message.text and message.text.strip().startswith('/'):
        cmd = message.text.strip().split()[0]
        allowed_cmds = ['/new', '/stop']
        if cmd not in allowed_cmds:
            await message.reply('Unknown command')
            return

    # For unsupported file types, reply with an error message instead of ignoring silently or crashing
    if message.content_type in ("audio", "video", "video_note", "poll", "sticker", "voice", "document", "game", "giveaway", "location", "venue"):
        await message.reply("File type does not suported")
        return

    # Save images if present
    imgs = []
    if message.photo:
        photo = message.photo[-1]
        try:
            bio = io.BytesIO()
            await bot.download(photo, destination=bio)
            bio.seek(0)
            
            os.makedirs(LOADED_IMAGE_DIR, exist_ok=True)
            img_path = os.path.join(LOADED_IMAGE_DIR, f"{photo.file_unique_id}.jpg")
            with open(img_path, "wb") as f:
                f.write(bio.read())
            
            compress_image_to_2mp(img_path)
            imgs.append(img_path)
        except Exception as e:
            logger.exception("Failed to process photo: %s", e)
    if len(imgs) > MAX_IMAGES:
        await bot.send_message(user_id, f"Please send up to {MAX_IMAGES} images")
        return
    
    await pipeline_queue.put(
        {
            "chat_id": user_id,
            "message_text": (message.caption or message.text or "[NO ENCHANCE]"),
            "image_path": imgs
        }
    )
    await bot.send_message(user_id, "Task added to queue. Please wait for your turn.")
    
# UTILITY

def compress_image_to_2mp(image_path: str) -> None:
    try:
        with Image.open(image_path) as img:
            width, height = img.size
            total_pixels = width * height
            if total_pixels > 2000000:
                scale = math.sqrt(2000000 / total_pixels)
                new_width = int(width * scale)
                new_height = int(height * scale)
                resample_filter = getattr(Image, 'Resampling', Image).LANCZOS
                resized_img = img.resize((new_width, new_height), resample=resample_filter)
                resized_img.save(image_path, format=img.format or 'JPEG')
    except Exception as e:
        logging.getLogger(__name__).warning(f"Error compressing image {image_path}: {e}")

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    asyncio.run(main())