import asyncio
import re
import PTN
from Backend.helper.imdb import get_detail, get_season, search_title
from Backend.helper.pyro import extract_tmdb_id, normalize_languages
from themoviedb import aioTMDb
from Backend.config import Telegram
import Backend
from Backend.logger import LOGGER
import traceback


DELAY = 2

tmdb = aioTMDb(key=Telegram.TMDB_API, language="en-US", region="US")


def detect_episode_pack(filename: str, parsed: dict) -> dict:
    name = filename.replace(".", " ").replace("_", " ")
    lower_name = name.lower()
    season = parsed.get("season")
    episode = parsed.get("episode")

    range_patterns = [
        r"\bs(?:eason)?\s*0*(\d{1,2})\s*e(?:p(?:isode)?)?\s*0*(\d{1,3})\s*(?:-|–|—|~|\bto\b)\s*(?:e(?:p(?:isode)?)?)?\s*0*(\d{1,3})\b",
        r"\bs(?:eason)?\s*0*(\d{1,2})\s*[\[\(\{]\s*0*(\d{1,3})\s*(?:-|–|—|~|\bto\b)\s*0*(\d{1,3})\s*[\]\)\}]",
        r"\bseason\s*0*(\d{1,2}).*?\b(?:ep|episode|episodes)\s*0*(\d{1,3})\s*(?:-|–|—|~|\bto\b)\s*0*(\d{1,3})\b",
    ]

    for pattern in range_patterns:
        match = re.search(pattern, lower_name, flags=re.IGNORECASE)
        if not match:
            continue
        season_number, start, end = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if end < start:
            start, end = end, start
        episode_numbers = list(range(start, end + 1))
        return {
            "kind": "episode_range",
            "season_number": season_number,
            "episode_start": start,
            "episode_end": end,
            "episode_numbers": episode_numbers,
            "pack_id": f"s{season_number:02d}e{start:02d}-e{end:02d}",
            "title": f"Episodes {start}-{end}",
        }

    if isinstance(episode, list) and season:
        episode_numbers = sorted({int(item) for item in episode if str(item).isdigit()})
        if episode_numbers:
            start, end = episode_numbers[0], episode_numbers[-1]
            return {
                "kind": "episode_range",
                "season_number": int(season),
                "episode_start": start,
                "episode_end": end,
                "episode_numbers": episode_numbers,
                "pack_id": f"s{int(season):02d}e{start:02d}-e{end:02d}",
                "title": f"Episodes {start}-{end}",
            }

    season_pack_keywords = (
        "combined",
        "complete",
        "complete season",
        "season pack",
        "full season",
        "all episodes",
        "batch",
    )
    has_pack_keyword = any(keyword in lower_name for keyword in season_pack_keywords)
    season_match = re.search(r"\bs(?:eason)?\s*0*(\d{1,2})\b", lower_name, flags=re.IGNORECASE)
    if has_pack_keyword and (season or season_match) and not episode:
        season_number = int(season if season else season_match.group(1))
        return {
            "kind": "season_pack",
            "season_number": season_number,
            "episode_start": None,
            "episode_end": None,
            "episode_numbers": [],
            "pack_id": f"s{season_number:02d}-complete",
            "title": f"Season {season_number} Complete",
        }

    return None


def pick_youtube_trailer(videos) -> str:
    results = getattr(videos, "results", None) or []
    youtube_videos = [
        video for video in results
        if getattr(video, "site", "") == "YouTube" and getattr(video, "key", None)
    ]
    preferred = next(
        (
            video for video in youtube_videos
            if getattr(video, "official", False)
            and getattr(video, "type", "") in ("Trailer", "Teaser")
        ),
        None,
    )
    fallback = next(
        (
            video for video in youtube_videos
            if getattr(video, "type", "") in ("Trailer", "Teaser")
        ),
        youtube_videos[0] if youtube_videos else None,
    )
    selected = preferred or fallback
    return f"https://www.youtube.com/embed/{selected.key}?autoplay=1&mute=0&loop=1&playlist={selected.key}&controls=0&playsinline=1" if selected else None


def format_cast(credits, limit: int = 10) -> list:
    cast_members = getattr(credits, "cast", None) or []
    formatted = []
    for member in cast_members[:limit]:
        profile_path = getattr(member, "profile_path", None)
        formatted.append({
            "id": getattr(member, "id", None),
            "name": getattr(member, "name", None) or getattr(member, "original_name", ""),
            "character": getattr(member, "character", "") or "",
            "profile": f"https://image.tmdb.org/t/p/w185{profile_path}" if profile_path else "",
        })
    return formatted


def _provider_value(provider, key: str, default=None):
    if isinstance(provider, dict):
        return provider.get(key, default)
    return getattr(provider, key, default)


def format_watch_providers(provider_response, region: str = "IN", limit: int = 8) -> list:
    results = _provider_value(provider_response, "results", {}) or {}
    region_data = results.get(region) or results.get(region.upper()) if isinstance(results, dict) else None
    if not region_data:
        return []

    formatted = []
    seen = set()
    for provider_type in ("flatrate", "free", "ads", "rent", "buy"):
        providers = _provider_value(region_data, provider_type, []) or []
        for provider in providers:
            provider_id = _provider_value(provider, "provider_id")
            provider_name = _provider_value(provider, "provider_name")
            logo_path = _provider_value(provider, "logo_path")
            if not provider_id or provider_id in seen:
                continue
            seen.add(provider_id)
            formatted.append({
                "provider_id": provider_id,
                "name": provider_name,
                "logo": tmdb_image(logo_path, "w92"),
                "type": provider_type,
                "region": region,
            })
            if len(formatted) >= limit:
                return formatted
    return formatted

async def metadata(filename: str, media) -> dict:
    try:
        parsed = PTN.parse(filename)

        title = parsed.get('title')
        season = parsed.get('season')
        episode = parsed.get('episode')
        year = parsed.get('year')
        quality = parsed.get('resolution')
        languages = normalize_languages(parsed.get('language'))
        rip = parsed.get('quality')
        pack_info = detect_episode_pack(filename, parsed)

        if isinstance(season, list):
            LOGGER.warning(f"Invalid format: Season is list — {filename}, parsed: {parsed}")
            return None

        if isinstance(episode, list) and not pack_info:
            LOGGER.warning(f"Invalid format: Episode is list without detectable pack — {filename}, parsed: {parsed}")
            return None

        if season and not episode and not pack_info:
            LOGGER.warning(f"Missing episode for season: {filename}, parsed: {parsed}")
            return None

        try:
            default_id = extract_tmdb_id(Backend.USE_DEFAULT_ID)
        except Exception as e:
            LOGGER.debug(f"Failed to extract default TMDB ID from USE_DEFAULT_ID: {e}")
            default_id = None

        if not default_id:
            try:
                default_id = extract_tmdb_id(filename)
            except Exception as e:
                LOGGER.debug(f"Failed to extract TMDB ID from filename {filename}: {e}")
                default_id = None

        if title:
            if pack_info:
                LOGGER.info(
                    "Fetching TV metadata for pack: "
                    f"{title} S{pack_info['season_number']} {pack_info['pack_id']}"
                )
                return await fetch_tv_pack_metadata(title, pack_info, year, quality, default_id, languages, rip)
            elif season and episode:
                LOGGER.info(f"Fetching TV metadata for: {title} S{season}E{episode}")
                return await fetch_tv_metadata(title, season, episode, year, quality, default_id, languages, rip)
            else:
                LOGGER.info(f"Fetching movie metadata for: {title} ({year})")
                return await fetch_movie_metadata(title, year, quality, default_id, languages, rip)

        LOGGER.info(f"No title parsed from: {filename} (parsed: {parsed})")
        return None

    except Exception as e:
        LOGGER.error(f"Unhandled error while parsing metadata for {filename}: {e}")
        return None




async def fetch_tv_metadata(title: str, season: int, episode: int, year=None, quality=None, default_id=None, languages=None, rip=None) -> dict:
    try:
        tv_details, ep_details, use_tmdb = None, None, Telegram.USE_TMDB
        imdb_id = default_id if not use_tmdb and default_id and default_id.startswith("tt") else None

        if not use_tmdb and not imdb_id:
            try:
                result = await search_title(
                    query=f"{title} {year}" if year else title,
                    type="tvSeries",
                )
                imdb_id = result['id'] if result else None
            except Exception as e:
                LOGGER.warning(f"IMDb TV search failed for '{title}': {e}")
                imdb_id = None

        if not use_tmdb and imdb_id:
            try:
                clean_id = imdb_id[2:] if imdb_id.startswith("tt") else imdb_id
                await asyncio.sleep(DELAY)
                tv_details = await get_detail(imdb_id=clean_id)
                await asyncio.sleep(DELAY)
                ep_details = await get_season(imdb_id=clean_id, season_id=season, episode_id=episode)
            except Exception as e:
                LOGGER.warning(f"IMDb TV fetch failed for ID {imdb_id}: {e}")
                tv_details, ep_details = None, None

        if use_tmdb or not tv_details or not ep_details:
            use_tmdb = True
            await asyncio.sleep(DELAY)
            tmdb_results = await tmdb.search().tv(query=title)
            if not tmdb_results:
                LOGGER.warning(f"No TMDb results found for title '{title}'")
                return None
            tv_id = tmdb_results[0].id
            LOGGER.debug(f"TMDb ID found: {tv_id}")
            tv_details = await tmdb.tv(tv_id).details()
            ep_details = await tmdb.episode(tv_id, season, episode).details()

        if use_tmdb:
            tmdb_id = tv_details.id
            show_title = tv_details.name
            show_year = tv_details.first_air_date.year if tv_details.first_air_date else 0
            rate = tv_details.vote_average or 0
            vote_count = getattr(tv_details, "vote_count", 0) or 0
            popularity = getattr(tv_details, "popularity", 0) or 0
            description = tv_details.overview or ''
            total_seasons = tv_details.number_of_seasons or 0
            total_episodes = tv_details.number_of_episodes or 0
            poster = f"https://image.tmdb.org/t/p/w500{tv_details.poster_path}" if tv_details.poster_path else ''
            backdrop = f"https://image.tmdb.org/t/p/original{tv_details.backdrop_path}" if tv_details.backdrop_path else ''
            status = tv_details.status or 'Unknown'
            genres = [genre.name for genre in tv_details.genres] if tv_details.genres else []
            ep_title = ep_details.name if ep_details and hasattr(ep_details, 'name') else f"S{season}E{episode}"
            ep_backdrop = f"https://image.tmdb.org/t/p/original{ep_details.still_path}" if ep_details and ep_details.still_path else ''
            try:
                trailer_url = pick_youtube_trailer(await tmdb.tv(tmdb_id).videos())
            except Exception as e:
                LOGGER.warning(f"TV trailer fetch failed for {show_title}: {e}")
                trailer_url = None
            try:
                cast = format_cast(await tmdb.tv(tmdb_id).credits())
            except Exception as e:
                LOGGER.warning(f"TV cast fetch failed for {show_title}: {e}")
                cast = []
            try:
                watch_providers = format_watch_providers(await tmdb.tv(tmdb_id).watch_providers())
            except Exception as e:
                LOGGER.warning(f"TV watch provider fetch failed for {show_title}: {e}")
                watch_providers = []
        else:
            tmdb_id = tv_details['id'].replace("tt", "")
            show_title = tv_details.get('title', title)
            show_year = tv_details.get('releaseDetailed', {}).get('year', 0)
            rate = tv_details.get('rating', {}).get('star', 0)
            vote_count = tv_details.get('rating', {}).get('count', 0) or 0
            popularity = 0
            description = tv_details.get('plot', '')
            total_seasons = len(tv_details.get('all_seasons', []))
            total_episodes = sum(len(season.get('episodes', [])) for season in tv_details.get('seasons', []))
            poster = tv_details.get('image', '')
            backdrop = ''
            genres = tv_details.get('genre', [])
            ep_title = ep_details.get('title', f"S{season}E{episode}") if ep_details else f"S{season}E{episode}"
            ep_backdrop = ep_details.get('image', '') if ep_details else ''
            trailer_url = None
            cast = []
            watch_providers = []
            try:
                await asyncio.sleep(DELAY)
                fallback_results = await tmdb.search().tv(query=show_title)
                if fallback_results:
                    fallback_id = fallback_results[0].id
                    fallback_detail = await tmdb.tv(fallback_id).details()
                    backdrop = f"https://image.tmdb.org/t/p/original{fallback_detail.backdrop_path}" if fallback_detail.backdrop_path else ''
                    status = fallback_detail.status or 'Unknown'
                else:
                    status = 'Unknown'
            except Exception as e:
                LOGGER.warning(f"Fallback TMDb metadata fetch failed: {e}")
                status = 'Unknown'

        result = {
            "tmdb_id": tmdb_id,
            "title": show_title,
            "year": show_year,
            "rate": rate,
            "vote_count": vote_count,
            "popularity": popularity,
            "description": description,
            "total_seasons": total_seasons,
            "total_episodes": total_episodes,
            "poster": poster,
            "backdrop": backdrop,
            "trailer_url": trailer_url,
            "cast": cast,
            "watch_providers": watch_providers,
            "status": status,
            "genres": genres,
            "media_type": "tv",
            "season_number": season,
            "episode_number": episode,
            "episode_title": ep_title,
            "episode_backdrop": ep_backdrop,
            "quality": quality,
            "languages": languages or ['hi'],
            "rip": rip or 'Blu-ray'
        }

        LOGGER.info(f"Metadata successfully fetched for {show_title} S{season}E{episode}")
        return result

    except Exception as e:
        LOGGER.error(f"Error fetching TV metadata for '{title}' S{season}E{episode}: {e}", exc_info=True)
        return None


def tmdb_image(path: str, size: str = "original") -> str:
    return f"https://image.tmdb.org/t/p/{size}{path}" if path else ''


def format_pack_episode(ep_details, episode_number: int) -> dict:
    return {
        "episode_number": episode_number,
        "title": getattr(ep_details, "name", None) or f"Episode {episode_number}",
        "overview": getattr(ep_details, "overview", "") or "",
        "episode_backdrop": tmdb_image(getattr(ep_details, "still_path", None)),
        "runtime": getattr(ep_details, "runtime", None),
    }


async def fetch_tv_pack_metadata(title: str, pack_info: dict, year=None, quality=None, default_id=None, languages=None, rip=None) -> dict:
    try:
        if not Telegram.USE_TMDB:
            LOGGER.info("TV packs use TMDb episode data for reliable range/season metadata")

        await asyncio.sleep(DELAY)
        tmdb_results = await tmdb.search().tv(query=title)
        if not tmdb_results:
            LOGGER.warning(f"No TMDb results found for pack title '{title}'")
            return None

        tv_id = tmdb_results[0].id
        LOGGER.debug(f"TMDb ID found for pack: {tv_id}")
        tv_details = await tmdb.tv(tv_id).details()
        season_number = int(pack_info["season_number"])
        episode_numbers = pack_info.get("episode_numbers") or []
        pack_episodes = []

        if pack_info["kind"] == "season_pack":
            season_details = await tmdb.season(tv_id, season_number).details()
            season_episodes = getattr(season_details, "episodes", None) or []
            episode_numbers = [
                int(getattr(ep, "episode_number"))
                for ep in season_episodes
                if getattr(ep, "episode_number", None)
            ]
            pack_episodes = [
                format_pack_episode(ep, int(getattr(ep, "episode_number")))
                for ep in season_episodes
                if getattr(ep, "episode_number", None)
            ]
        else:
            for episode_number in episode_numbers:
                try:
                    ep_details = await tmdb.episode(tv_id, season_number, episode_number).details()
                    pack_episodes.append(format_pack_episode(ep_details, episode_number))
                except Exception as e:
                    LOGGER.warning(f"Episode detail fetch failed for {title} S{season_number}E{episode_number}: {e}")
                    pack_episodes.append({
                        "episode_number": episode_number,
                        "title": f"Episode {episode_number}",
                        "overview": "",
                        "episode_backdrop": "",
                        "runtime": None,
                    })

        representative_backdrop = next(
            (episode["episode_backdrop"] for episode in pack_episodes if episode.get("episode_backdrop")),
            tmdb_image(getattr(tv_details, "backdrop_path", None)),
        )

        if pack_info["kind"] == "season_pack":
            pack_title = f"Season {season_number} Complete"
        else:
            start = pack_info.get("episode_start")
            end = pack_info.get("episode_end")
            start_title = next((ep["title"] for ep in pack_episodes if ep["episode_number"] == start), "")
            end_title = next((ep["title"] for ep in pack_episodes if ep["episode_number"] == end), "")
            title_suffix = f": {start_title} - {end_title}" if start_title and end_title and start_title != end_title else ""
            pack_title = f"Episodes {start}-{end}{title_suffix}"

        try:
            trailer_url = pick_youtube_trailer(await tmdb.tv(tv_details.id).videos())
        except Exception as e:
            LOGGER.warning(f"TV trailer fetch failed for pack {tv_details.name}: {e}")
            trailer_url = None
        try:
            cast = format_cast(await tmdb.tv(tv_details.id).credits())
        except Exception as e:
            LOGGER.warning(f"TV cast fetch failed for pack {tv_details.name}: {e}")
            cast = []
        try:
            watch_providers = format_watch_providers(await tmdb.tv(tv_details.id).watch_providers())
        except Exception as e:
            LOGGER.warning(f"TV watch provider fetch failed for pack {tv_details.name}: {e}")
            watch_providers = []

        result = {
            "tmdb_id": tv_details.id,
            "title": tv_details.name,
            "year": tv_details.first_air_date.year if tv_details.first_air_date else 0,
            "rate": tv_details.vote_average or 0,
            "vote_count": getattr(tv_details, "vote_count", 0) or 0,
            "popularity": getattr(tv_details, "popularity", 0) or 0,
            "description": tv_details.overview or '',
            "total_seasons": tv_details.number_of_seasons or 0,
            "total_episodes": tv_details.number_of_episodes or 0,
            "poster": tmdb_image(getattr(tv_details, "poster_path", None), "w500"),
            "backdrop": tmdb_image(getattr(tv_details, "backdrop_path", None)),
            "trailer_url": trailer_url,
            "cast": cast,
            "watch_providers": watch_providers,
            "status": tv_details.status or 'Unknown',
            "genres": [genre.name for genre in tv_details.genres] if tv_details.genres else [],
            "media_type": "tv",
            "season_number": season_number,
            "pack": {
                "pack_id": pack_info["pack_id"],
                "kind": pack_info["kind"],
                "title": pack_title,
                "episode_start": pack_info.get("episode_start"),
                "episode_end": pack_info.get("episode_end"),
                "episode_numbers": episode_numbers,
                "episodes": pack_episodes,
                "backdrop": representative_backdrop,
            },
            "quality": quality,
            "languages": languages or ['hi'],
            "rip": rip or 'Blu-ray'
        }

        LOGGER.info(f"Pack metadata successfully fetched for {tv_details.name} {pack_info['pack_id']}")
        return result

    except Exception as e:
        LOGGER.error(f"Error fetching TV pack metadata for '{title}': {e}", exc_info=True)
        return None




async def fetch_movie_metadata(title: str, year=None, quality=None, default_id=None, languages=None, rip=None) -> dict:
    try:
        movie_details, use_tmdb = None, Telegram.USE_TMDB
        imdb_id = default_id if not use_tmdb and default_id and default_id.startswith("tt") else None

        if not use_tmdb and not imdb_id:
            try:
                result = await search_title(query=f"{title} {year}" if year else title, type="movie")
                imdb_id = result['id'] if result else None

            except Exception as e:
                LOGGER.warning(f"IMDb search failed for '{title}': {e}")
                imdb_id = None

        if not use_tmdb and imdb_id:
            try:
                clean_id = imdb_id[2:] if imdb_id.startswith("tt") else imdb_id
                LOGGER.debug(f"Fetching IMDb details using ID: {clean_id}")
                movie_details = await get_detail(imdb_id=clean_id)

            except Exception as e:
                LOGGER.warning(f"IMDb movie fetch failed for '{title}': {e}")
                movie_details = None

        if use_tmdb or not movie_details:
            use_tmdb = True
            try:
                tmdb_results = await tmdb.search().movies(query=title, year=year) if year else await tmdb.search().movies(query=title)
                if not tmdb_results:
                    LOGGER.warning(f"No TMDB results found for '{title}'")
                    return None
                movie_id = tmdb_results[0].id
                movie_details = await tmdb.movie(movie_id).details()
            except Exception as e:
                LOGGER.error(f"TMDB search failed for '{title}': {e}")
                return None

        if use_tmdb:
            tmdb_id = movie_details.id
            movie_title = movie_details.title
            movie_year = movie_details.release_date.year if movie_details.release_date else 0
            rate = movie_details.vote_average or 0
            vote_count = getattr(movie_details, "vote_count", 0) or 0
            popularity = getattr(movie_details, "popularity", 0) or 0
            description = movie_details.overview or ''
            poster = f"https://image.tmdb.org/t/p/w500{movie_details.poster_path}" if movie_details.poster_path else ''
            backdrop = f"https://image.tmdb.org/t/p/original{movie_details.backdrop_path}" if movie_details.backdrop_path else ''
            runtime = movie_details.runtime or 0
            genres = [genre.name for genre in movie_details.genres] if movie_details.genres else []
            try:
                trailer_url = pick_youtube_trailer(await tmdb.movie(tmdb_id).videos())
            except Exception as e:
                LOGGER.warning(f"Movie trailer fetch failed for {movie_title}: {e}")
                trailer_url = None
            try:
                cast = format_cast(await tmdb.movie(tmdb_id).credits())
            except Exception as e:
                LOGGER.warning(f"Movie cast fetch failed for {movie_title}: {e}")
                cast = []
            try:
                watch_providers = format_watch_providers(await tmdb.movie(tmdb_id).watch_providers())
            except Exception as e:
                LOGGER.warning(f"Movie watch provider fetch failed for {movie_title}: {e}")
                watch_providers = []
        else:
            description = movie_details.get('plot', '')
            tmdb_id = movie_details['id'].replace("tt", "")
            movie_title = movie_details.get('title', title)
            movie_year = movie_details.get('releaseDetailed', {}).get('year', 0)
            rate = movie_details.get('rating', {}).get('star', 0)
            vote_count = movie_details.get('rating', {}).get('count', 0) or 0
            popularity = 0
            runtime = movie_details.get('runtimeSeconds', 0) // 60
            genres = movie_details.get('genre', [])
            trailer_url = None
            cast = []
            watch_providers = []
            try:
                force_tmdb_results = await tmdb.search().movies(query=movie_title, year=movie_year)
                force_movie_id = force_tmdb_results[0].id
                force_movie_details = await tmdb.movie(force_movie_id).details()
                backdrop = f"https://image.tmdb.org/t/p/original{force_movie_details.backdrop_path}" if force_movie_details.backdrop_path else ''
                poster = movie_details.get('image', '') or \
                         (f"https://image.tmdb.org/t/p/w500{force_movie_details.poster_path}" if force_movie_details.poster_path else '')
            except Exception as e:
                backdrop = ''
                poster = ''

        LOGGER.info(f"Metadata fetched successfully for '{movie_title}' ({movie_year})")
        return {
            "tmdb_id": tmdb_id,
            "title": movie_title,
            "year": movie_year,
            "rate": rate,
            "vote_count": vote_count,
            "popularity": popularity,
            "description": description,
            "poster": poster,
            "backdrop": backdrop,
            "trailer_url": trailer_url,
            "cast": cast,
            "watch_providers": watch_providers,
            "media_type": "movie",
            "genres": genres,
            "runtime": runtime,
            "quality": quality,
            "languages": languages or ['hi'],
            "rip": rip or 'Blu-ray'
        }

    except Exception as e:
        LOGGER.error(f"Unhandled error in fetch_movie_metadata for '{title}': {e}")
        return None
