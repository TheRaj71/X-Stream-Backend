from asyncio import get_event_loop, sleep as asleep
from traceback import format_exc
from pyrogram import idle
import requests
import threading
import time
import random
from Backend import __version__, db
from Backend.logger import LOGGER
from Backend.fastapi import server
from Backend.helper.pyro import restart_notification
from Backend.pyrofork import StreamBot
from Backend.pyrofork.clients import initialize_clients

loop = get_event_loop()

def keep_awake():
    """Keep the Render service alive by pinging it periodically"""
    render_url = "https://x-stream-backend.onrender.com"
    while True:
        try:
            response = requests.get(render_url, timeout=30)
            LOGGER.info(f"Keep-alive ping successful: {response.status_code}")
            sleep_time = random.uniform(3, 14) * 60  # Random sleep time between 3 and 14 minutes
            time.sleep(sleep_time)
        except Exception as e:
            LOGGER.error(f"Error keeping app awake: {e}")
            sleep_time = random.uniform(3, 14) * 60  # Ensure we wait even if there's an error
            time.sleep(sleep_time)

async def start_services():
    try:
        LOGGER.info(f"Initializing Project-Stream v-{__version__}")
        await asleep(1.2)
        
        await db.connect()
        await asleep(1.2)
        
        await StreamBot.start()
        StreamBot.username = StreamBot.me.username
        LOGGER.info(f"Bot Client : [@{StreamBot.username}]")

        await asleep(1.2)
        LOGGER.info("Initializing Multi Clients...")
        await initialize_clients()

        await asleep(2)
        LOGGER.info('Initializing Project-S Web Server...')
        await restart_notification()
        loop.create_task(server.serve())

        # Start keep-alive service
        LOGGER.info("Starting keep-alive service...")
        keep_alive_thread = threading.Thread(target=keep_awake, daemon=True)
        keep_alive_thread.start()

        LOGGER.info("Project-S Started Successfully!")
        await idle()
    except Exception:
        LOGGER.error("Error during startup:\n" + format_exc())

async def stop_services():
    try:
        LOGGER.info("Stopping services...")
        await StreamBot.stop()
        await db.disconnect()
        LOGGER.info("Services stopped successfully.")
    except Exception:
        LOGGER.error("Error during shutdown:\n" + format_exc())

if __name__ == '__main__':
    try:
        loop.run_until_complete(start_services())
    except KeyboardInterrupt:
        LOGGER.info('Service Stopping...')
    except Exception:
        LOGGER.error(format_exc())
    finally:
        loop.run_until_complete(stop_services())
        loop.stop()
