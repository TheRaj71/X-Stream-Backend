import json
from os import getenv, path
from dotenv import load_dotenv
from Backend import LOGGER


load_dotenv(path.join(path.dirname(path.dirname(__file__)), "config.env"))
class Telegram:
    API_ID = int(getenv("API_ID", "0"))
    API_HASH = getenv("API_HASH", "")
    BOT_TOKEN = getenv("BOT_TOKEN", "")
    PORT = int(getenv("PORT", "8000"))
    BASE_URL = getenv("BASE_URL", "0.0.0.0").rstrip('/')
    AUTH_CHANNEL = [channel.strip() for channel in (getenv("AUTH_CHANNEL") or "").split(",") if channel.strip()]
    DATABASE = getenv("DATABASE", "")
    TMDB_API = getenv("TMDB_API", "")
    IMDB_API = getenv("IMDB_API", "")
    UPSTREAM_REPO = getenv("UPSTREAM_REPO", "")
    UPSTREAM_BRANCH = getenv("UPSTREAM_BRANCH", "main")
    MULTI_CLIENT = getenv("MULTI_CLIENT", "False").lower() == "true"
    USE_CAPTION = getenv("USE_CAPTION", "False").lower() == "true"
    USE_TMDB = getenv("USE_TMDB", "False").lower() == "true"
    OWNER_ID = int(getenv("OWNER_ID", "5422223708"))
    USE_DEFAULT_ID = getenv("USE_DEFAULT_ID", None)
    APPWRITE_ENDPOINT = getenv("APPWRITE_ENDPOINT", "https://fra.cloud.appwrite.io/v1").rstrip("/")
    # Keep the legacy names as fallbacks so an existing Render environment does
    # not silently lose access after moving the Appwrite settings server-side.
    APPWRITE_PROJECT_ID = getenv("APPWRITE_PROJECT_ID") or getenv("VITE_APPWRITE_PROJECT_ID", "")
    APPWRITE_API_KEY = getenv("APPWRITE_API_KEY") or getenv("APPWRITE_KEY", "")
    APPWRITE_DATABASE_ID = getenv("APPWRITE_DATABASE_ID", "clientportal")
    APPWRITE_SUBSCRIPTIONS_TABLE_ID = getenv("APPWRITE_SUBSCRIPTIONS_TABLE_ID", "subscriptions")
    APPWRITE_WATCHLIST_TABLE_ID = getenv("APPWRITE_WATCHLIST_TABLE_ID", "watchlist")
    STREMIO_AUTH_REQUIRED = getenv("STREMIO_AUTH_REQUIRED", "False").lower() == "true"
    STREMIO_AUTH_SECRET = getenv("STREMIO_AUTH_SECRET", "")
