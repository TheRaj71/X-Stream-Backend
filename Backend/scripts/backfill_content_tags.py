import argparse
import asyncio
from datetime import datetime

from Backend import db
from Backend.helper.metadata import (
    _tmdb_origin_country,
    _tmdb_original_language,
    _tmdb_production_countries,
    build_content_tags,
    tmdb,
)
from Backend.logger import LOGGER


async def _tmdb_details(media_type: str, tmdb_id: int):
    if media_type == "movie":
        return await tmdb.movie(tmdb_id).details()
    return await tmdb.tv(tmdb_id).details()


async def _backfill_collection(collection, media_type: str, limit: int) -> int:
    query = {
        "$or": [
            {"content_tags": {"$exists": False}},
            {"content_tags": []},
            {"origin_country": {"$exists": False}},
            {"production_countries": {"$exists": False}},
            {"original_language": {"$exists": False}},
        ]
    }
    cursor = collection.find(query, {"tmdb_id": 1, "genres": 1, "title": 1}).limit(limit)
    updated = 0

    async for document in cursor:
        tmdb_id = document.get("tmdb_id")
        if not tmdb_id:
            continue

        try:
            details = await _tmdb_details(media_type, int(tmdb_id))
            genres = [genre.name for genre in details.genres] if getattr(details, "genres", None) else document.get("genres", [])
            original_language = _tmdb_original_language(details)
            origin_country = _tmdb_origin_country(details)
            production_countries = _tmdb_production_countries(details)
            content_tags = build_content_tags(media_type, genres, original_language, origin_country, production_countries)

            await collection.update_one(
                {"_id": document["_id"]},
                {
                    "$set": {
                        "genres": genres,
                        "original_language": original_language,
                        "origin_country": origin_country,
                        "production_countries": production_countries,
                        "content_tags": content_tags,
                        "updated_on": datetime.utcnow(),
                    }
                },
            )
            updated += 1
            LOGGER.info("Backfilled %s %s - %s", media_type, tmdb_id, document.get("title"))
        except Exception as exc:
            LOGGER.warning("Backfill failed for %s %s: %s", media_type, tmdb_id, exc)

    return updated


async def main(limit: int):
    await db.connect()
    try:
        movie_limit = max(limit, 0)
        tv_limit = max(limit, 0)
        movie_count = await _backfill_collection(db.movie_collection, "movie", movie_limit)
        tv_count = await _backfill_collection(db.tv_collection, "tv", tv_limit)
        print(f"Backfilled {movie_count} movies and {tv_count} TV shows.")
    finally:
        await db.disconnect()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill TMDB-derived content category tags.")
    parser.add_argument("--limit", type=int, default=500, help="Maximum records per media type to process.")
    args = parser.parse_args()
    asyncio.run(main(args.limit))
