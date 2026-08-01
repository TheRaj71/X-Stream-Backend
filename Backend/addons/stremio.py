from asyncio import to_thread
from math import floor
from re import escape
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, unquote_plus

from fastapi import APIRouter, Header, HTTPException, Request

from Backend import __version__, db
from Backend.config import Telegram
from Backend.helper.appwrite_admin import AppwriteAdmin, AppwriteAdminError


router = APIRouter(prefix="/stremio", tags=["stremio-addon"])

ADDON_ID = "org.xstream.backend"
ADDON_NAME = "X-Stream"
CATALOG_MOVIES = "xstream-movies"
CATALOG_SERIES = "xstream-series"
PAGE_SIZE = 50
GENRE_OPTIONS = [
    "Action", "Adventure", "Animation", "Comedy", "Crime", "Documentary",
    "Drama", "Family", "Fantasy", "History", "Horror", "Mystery",
    "Romance", "Science Fiction", "Thriller", "War", "Western",
]
FEATURED_GENRES = [
    "Action", "Romance", "Comedy", "Thriller", "Horror", "Drama",
    "Science Fiction", "Crime", "Fantasy",
]
KDRAMA_LANGUAGES = ["ko", "Korean"]
LANGUAGE_CATALOGS = {
    "xstream-hindi": "Hindi",
    "xstream-english": "English",
    "xstream-tamil": "Tamil",
    "xstream-telugu": "Telugu",
}
QUALITY_CATALOGS = {
    "xstream-4k": ("2160p|4k|uhd", "4K Picks"),
}
CATALOGS = {
    "xstream-trending-movies": {"type": "movie", "name": "Trending", "source": "trending", "poster_shape": "landscape"},
    "xstream-trending-series": {"type": "series", "name": "Trending", "source": "trending", "poster_shape": "landscape"},
    CATALOG_MOVIES: {"type": "movie", "name": "Latest", "source": "sort", "sort": [("updated_on", "desc")]},
    CATALOG_SERIES: {"type": "series", "name": "Latest", "source": "sort", "sort": [("updated_on", "desc")]},
    "xstream-top-movies": {"type": "movie", "name": "Top Rated", "source": "sort", "sort": [("rating", "desc"), ("vote_count", "desc")]},
    "xstream-top-series": {"type": "series", "name": "Top Rated", "source": "sort", "sort": [("rating", "desc"), ("vote_count", "desc")]},
    "xstream-popular-movies": {"type": "movie", "name": "Popular", "source": "sort", "sort": [("popularity", "desc"), ("rating", "desc")]},
    "xstream-popular-series": {"type": "series", "name": "Popular", "source": "sort", "sort": [("popularity", "desc"), ("rating", "desc")]},
    "xstream-editors-movies": {"type": "movie", "name": "Editors Choice", "source": "editors", "poster_shape": "landscape"},
    "xstream-editors-series": {"type": "series", "name": "Editors Choice", "source": "editors", "poster_shape": "landscape"},
    "xstream-kdrama-series": {"type": "series", "name": "K-Drama Series", "source": "kdrama", "poster_shape": "landscape"},
    "xstream-kdrama-movies": {"type": "movie", "name": "K-Drama Movies", "source": "kdrama", "poster_shape": "landscape"},
    "xstream-anime-movies": {"type": "movie", "name": "Anime", "source": "anime", "poster_shape": "landscape"},
    "xstream-anime-series": {"type": "series", "name": "Anime", "source": "anime", "poster_shape": "landscape"},
}

for genre in FEATURED_GENRES:
    catalog_slug = genre.lower().replace(" ", "-")
    CATALOGS[f"xstream-genre-{catalog_slug}-movies"] = {
        "type": "movie",
        "name": genre,
        "source": "genre",
        "genre": genre,
        "poster_shape": "landscape",
    }
    if genre == "Romance":
        continue

    CATALOGS[f"xstream-genre-{catalog_slug}-series"] = {
        "type": "series",
        "name": genre,
        "source": "genre",
        "genre": genre,
        "poster_shape": "landscape",
    }

for catalog_id, language in LANGUAGE_CATALOGS.items():
    CATALOGS[f"{catalog_id}-movies"] = {
        "type": "movie",
        "name": language,
        "source": "language",
        "language": language,
    }
    CATALOGS[f"{catalog_id}-series"] = {
        "type": "series",
        "name": language,
        "source": "language",
        "language": language,
    }

for catalog_id, (quality, name) in QUALITY_CATALOGS.items():
    CATALOGS[f"{catalog_id}-movies"] = {
        "type": "movie",
        "name": name,
        "source": "quality",
        "quality": quality,
        "poster_shape": "landscape",
    }
    CATALOGS[f"{catalog_id}-series"] = {
        "type": "series",
        "name": name,
        "source": "quality",
        "quality": quality,
        "poster_shape": "landscape",
    }

CATALOGS["xstream-season-packs"] = {
    "type": "series",
    "name": "Season Packs",
    "source": "season_packs",
    "poster_shape": "landscape",
}


def _as_dict(value: Any) -> Dict[str, Any]:
    if hasattr(value, "dict"):
        return value.dict()
    return dict(value or {})


def _absolute_base_url(request: Request) -> str:
    # Prefer the configured public Render URL so generated links stay HTTPS behind the proxy.
    configured_url = Telegram.BASE_URL
    if configured_url and configured_url not in ("0.0.0.0", "127.0.0.1", "localhost"):
        return configured_url.rstrip("/")

    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",", 1)[0].strip()
    if forwarded_host:
        return f"{forwarded_proto}://{forwarded_host.rstrip('/') }"
    return str(request.base_url).rstrip("/")

def _clean_items(items: Iterable[Any]) -> List[Dict[str, Any]]:
    return [_as_dict(item) for item in items]


def _parse_extra(extra: Optional[str]) -> Dict[str, str]:
    parsed: Dict[str, str] = {}
    if not extra:
        return parsed

    for part in extra.split("&"):
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        parsed[unquote_plus(key)] = unquote_plus(value)
    return parsed


def _extra_int(params: Dict[str, str], name: str, default: int = 0) -> int:
    try:
        return max(int(params.get(name, default)), 0)
    except (TypeError, ValueError):
        return default


def _page_from_skip(skip: int) -> int:
    return floor(skip / PAGE_SIZE) + 1


def _genre_from_params(params: Dict[str, str]) -> Optional[str]:
    genre = params.get("genre")
    return genre.strip() if genre and genre.strip() else None


def _matches_genre(document: Dict[str, Any], genre: Optional[str]) -> bool:
    if not genre:
        return True
    return genre.lower() in {str(item).lower() for item in document.get("genres") or []}


def _quality_regex(quality: str) -> Dict[str, str]:
    return {"$regex": quality, "$options": "i"}


def _exact_text_regex(value: str) -> Dict[str, str]:
    return {"$regex": f"^{escape(value)}$", "$options": "i"}


def _korean_content_query() -> Dict[str, Any]:
    missing_tags = {"$or": [{"content_tags": {"$exists": False}}, {"content_tags": []}]}
    return {
        "$or": [
            {"content_tags": _exact_text_regex("kdrama")},
            {"content_tags": _exact_text_regex("korean")},
            {"origin_country": _exact_text_regex("KR")},
            {"production_countries": _exact_text_regex("KR")},
            {"original_language": _exact_text_regex("ko")},
            *({"$and": [missing_tags, {"languages": _exact_text_regex(language)}]} for language in KDRAMA_LANGUAGES),
        ]
    }


def _anime_content_query() -> Dict[str, Any]:
    missing_tags = {"$or": [{"content_tags": {"$exists": False}}, {"content_tags": []}]}
    return {
        "$or": [
            {"content_tags": _exact_text_regex("anime")},
            {
                "$and": [
                    {"genres": _exact_text_regex("Animation")},
                    {
                        "$or": [
                            {"origin_country": {"$in": ["JP", "KR", "CN", "TW"]}},
                            {"production_countries": {"$in": ["JP", "KR", "CN", "TW"]}},
                            {"original_language": {"$in": ["ja", "ko", "zh", "cn"]}},
                        ]
                    },
                ]
            },
            {"$and": [missing_tags, {"genres": _exact_text_regex("Animation")}]},
        ]
    }


def _catalog_extra() -> List[Dict[str, Any]]:
    return [
        {"name": "search", "isRequired": False},
        {"name": "genre", "isRequired": False, "options": GENRE_OPTIONS},
        {"name": "skip", "isRequired": False},
    ]


def _parse_stremio_id(stremio_id: str) -> Tuple[int, Optional[int], Optional[int]]:
    parts = stremio_id.split(":")
    if len(parts) < 2 or parts[0] != "tmdb":
        raise HTTPException(status_code=400, detail="Use IDs like tmdb:12345 or tmdb:12345:1:2")

    try:
        tmdb_id = int(parts[1])
        season = int(parts[2]) if len(parts) > 2 else None
        episode = int(parts[3]) if len(parts) > 3 else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Stremio ID")

    return tmdb_id, season, episode


def _stremio_type(document: Dict[str, Any]) -> str:
    media_type = document.get("media_type") or document.get("type")
    return "movie" if media_type == "movie" else "series"


def _backend_media_type(content_type: str) -> str:
    return "movie" if content_type == "movie" else "tvshow"


def _result_key(content_type: str) -> str:
    return "movies" if content_type == "movie" else "tv_shows"


def _mongo_sort(sort_params: List[Tuple[str, str]]) -> List[Tuple[str, int]]:
    return [(field, -1 if direction == "desc" else 1) for field, direction in sort_params]


def _image_url(value: Any) -> Optional[str]:
    if not value:
        return None
    value = str(value)
    if value.startswith(("http://", "https://")):
        return value
    if value.startswith("/"):
        return f"https://image.tmdb.org/t/p/original{value}"
    return value


def _preview_meta(document: Dict[str, Any], poster_shape: str = "poster") -> Dict[str, Any]:
    media_type = _stremio_type(document)
    poster = document.get("backdrop") if poster_shape == "landscape" else document.get("poster")
    poster = poster or document.get("poster") or document.get("backdrop")
    return {
        "id": f"tmdb:{document.get('tmdb_id')}",
        "type": media_type,
        "name": document.get("title", "Untitled"),
        "poster": _image_url(poster),
        "posterShape": poster_shape,
        "background": _image_url(document.get("backdrop") or document.get("poster")),
        "description": document.get("description"),
        "releaseInfo": str(document.get("release_year") or ""),
        "imdbRating": str(document.get("rating") or ""),
        "genres": document.get("genres") or [],
    }


def _full_meta(document: Dict[str, Any]) -> Dict[str, Any]:
    meta = _preview_meta(document)
    meta.update({
        "runtime": document.get("runtime"),
    })

    if meta["type"] == "series":
        meta["videos"] = _series_videos(document)

    return {key: value for key, value in meta.items() if value not in (None, "", [])}


def _series_videos(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    videos_by_key: Dict[Tuple[int, int], Dict[str, Any]] = {}
    tmdb_id = document.get("tmdb_id")

    for season in document.get("seasons") or []:
        season_number = season.get("season_number")
        for episode in season.get("episodes") or []:
            _add_series_video(videos_by_key, tmdb_id, season_number, episode, document.get("backdrop"))

        for pack in season.get("packs") or []:
            pack_backdrop = pack.get("backdrop") or document.get("backdrop")
            pack_episodes = pack.get("episodes") or []
            if pack_episodes:
                for episode in pack_episodes:
                    _add_series_video(videos_by_key, tmdb_id, season_number, episode, pack_backdrop)
                continue

            for episode_number in _pack_episode_numbers(pack):
                _add_series_video(
                    videos_by_key,
                    tmdb_id,
                    season_number,
                    {"episode_number": episode_number, "title": f"Episode {episode_number}"},
                    pack_backdrop,
                )

    return sorted(videos_by_key.values(), key=lambda item: (item.get("season", 0), item.get("episode", 0)))


def _add_series_video(
    videos_by_key: Dict[Tuple[int, int], Dict[str, Any]],
    tmdb_id: Any,
    season_number: Optional[int],
    episode: Dict[str, Any],
    fallback_backdrop: Optional[str],
) -> None:
    episode_number = episode.get("episode_number")
    if season_number is None or episode_number is None:
        return

    key = (int(season_number), int(episode_number))
    videos_by_key[key] = {
        "id": f"tmdb:{tmdb_id}:{season_number}:{episode_number}",
        "title": episode.get("title") or f"Episode {episode_number}",
        "season": season_number,
        "episode": episode_number,
        "thumbnail": _image_url(episode.get("episode_backdrop") or fallback_backdrop),
    }


def _pack_episode_numbers(pack: Dict[str, Any]) -> List[int]:
    numbers = [int(number) for number in pack.get("episode_numbers") or [] if number is not None]
    if numbers:
        return sorted(set(numbers))

    start = pack.get("episode_start")
    end = pack.get("episode_end")
    if start is None or end is None:
        return []

    start, end = int(start), int(end)
    if end < start:
        start, end = end, start
    return list(range(start, end + 1))


def _stream_url(base_url: str, item: Dict[str, Any]) -> str:
    stream_id = quote(str(item.get("id")), safe="")
    stream_name = quote(str(item.get("name") or "video.mp4"), safe="")
    return f"{base_url}/dl/{stream_id}/{stream_name}"


def _stream_title(item: Dict[str, Any], prefix: str = "") -> str:
    parts = [prefix, item.get("quality"), item.get("size")]
    return " | ".join(str(part) for part in parts if part)


def _stream_items(base_url: str, items: Iterable[Dict[str, Any]], prefix: str = "") -> List[Dict[str, Any]]:
    streams: List[Dict[str, Any]] = []
    for item in items:
        if not item.get("id"):
            continue
        streams.append({
            "name": ADDON_NAME,
            "title": _stream_title(item, prefix=prefix),
            "url": _stream_url(base_url, item),
            "behaviorHints": {
                "filename": item.get("name"),
                "notWebReady": False,
            },
        })
    return streams


async def _authorized_stremio_user(access_token: Optional[str]) -> bool:
    if not Telegram.STREMIO_AUTH_REQUIRED:
        return True
    if not access_token:
        return False

    try:
        admin = AppwriteAdmin()
        user = await to_thread(admin.verify_stremio_token, access_token)
        return user is not None
    except Exception:
        return False


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


@router.get("/addon-link")
async def addon_link(request: Request, authorization: Optional[str] = Header(None)) -> Dict[str, str]:
    jwt = _bearer_token(authorization)
    if not jwt:
        raise HTTPException(status_code=401, detail="Missing Appwrite JWT")

    try:
        admin = AppwriteAdmin()
        user = await to_thread(admin.get_user_from_jwt, jwt)
    except AppwriteAdminError as error:
        raise HTTPException(status_code=503, detail="Addon service configuration is incomplete") from error
    token = await to_thread(admin.create_stremio_token, user)
    return {"addonUrl": f"{_absolute_base_url(request)}/stremio/{token}/manifest.json"}


async def _movie_streams(base_url: str, tmdb_id: int) -> List[Dict[str, Any]]:
    details = await db.get_media_details(tmdb_id=tmdb_id)
    if not details or details.get("type") != "movie":
        return []
    return _stream_items(base_url, details.get("telegram") or [])


async def _series_streams(
    base_url: str,
    tmdb_id: int,
    season_number: Optional[int],
    episode_number: Optional[int],
) -> List[Dict[str, Any]]:
    if season_number is None:
        details = await db.get_media_details(tmdb_id=tmdb_id)
        if not details or details.get("type") != "tv":
            return []

        streams: List[Dict[str, Any]] = []
        for season in details.get("seasons") or []:
            streams.extend(_stream_items(base_url, season.get("packs") or [], prefix=f"S{season.get('season_number')} Pack"))
        return streams

    season = await db.get_media_details(tmdb_id=tmdb_id, season_number=season_number)
    if not season:
        return []

    streams: List[Dict[str, Any]] = []
    if episode_number is not None:
        for episode in season.get("episodes") or []:
            if episode.get("episode_number") == episode_number:
                streams.extend(_stream_items(base_url, episode.get("telegram") or []))

        for pack in season.get("packs") or []:
            if _pack_contains_episode(pack, episode_number):
                streams.extend(_stream_items(base_url, pack.get("telegram") or [], prefix=pack.get("title") or "Pack"))
    else:
        streams.extend(_stream_items(base_url, season.get("packs") or [], prefix=f"S{season_number} Pack"))

    return streams


def _pack_contains_episode(pack: Dict[str, Any], episode_number: int) -> bool:
    if episode_number in _pack_episode_numbers(pack):
        return True

    return any(
        episode.get("episode_number") == episode_number
        for episode in pack.get("episodes") or []
    )


def _manifest_payload(authenticated: bool = True) -> Dict[str, Any]:
    catalogs = [
        {
            "type": definition["type"],
            "id": catalog_id,
            "name": definition["name"],
            "extra": _catalog_extra(),
        }
        for catalog_id, definition in CATALOGS.items()
    ] if authenticated else []

    return {
        "id": ADDON_ID,
        "version": __version__,
        "name": ADDON_NAME,
        "description": "Stream your X-Stream backend library in Stremio-compatible clients.",
        "resources": ["catalog", "meta", "stream"],
        "types": ["movie", "series"],
        "catalogs": catalogs,
        "idPrefixes": ["tmdb:"],
        "behaviorHints": {"configurable": False},
    }


@router.get("/manifest.json")
async def manifest() -> Dict[str, Any]:
    return _manifest_payload(authenticated=not Telegram.STREMIO_AUTH_REQUIRED)


@router.get("/{access_token}/manifest.json")
async def authenticated_manifest(access_token: str) -> Dict[str, Any]:
    return _manifest_payload(authenticated=await _authorized_stremio_user(access_token))


@router.get("/catalog/{content_type}/{catalog_id}.json")
@router.get("/catalog/{content_type}/{catalog_id}/{extra}.json")
async def catalog(content_type: str, catalog_id: str, extra: Optional[str] = None) -> Dict[str, Any]:
    if not await _authorized_stremio_user(None):
        return {"metas": []}
    return await _catalog_response(content_type, catalog_id, extra)


async def _catalog_response(content_type: str, catalog_id: str, extra: Optional[str] = None) -> Dict[str, Any]:
    params = _parse_extra(extra)
    catalog_definition = CATALOGS.get(catalog_id)

    if content_type not in ("movie", "series") or not catalog_definition:
        return {"metas": []}

    if catalog_definition["type"] != content_type:
        return {"metas": []}

    items = await _catalog_items(content_type, catalog_definition, params)
    poster_shape = catalog_definition.get("poster_shape", "poster")
    return {"metas": [_preview_meta(item, poster_shape=poster_shape) for item in items]}


@router.get("/{access_token}/catalog/{content_type}/{catalog_id}.json")
@router.get("/{access_token}/catalog/{content_type}/{catalog_id}/{extra}.json")
async def authenticated_catalog(
    access_token: str,
    content_type: str,
    catalog_id: str,
    extra: Optional[str] = None,
) -> Dict[str, Any]:
    if not await _authorized_stremio_user(access_token):
        return {"metas": []}
    return await _catalog_response(content_type, catalog_id, extra)


async def _catalog_items(content_type: str, catalog_definition: Dict[str, Any], params: Dict[str, str]) -> List[Dict[str, Any]]:
    search = params.get("search")
    genre = _genre_from_params(params)
    skip = _extra_int(params, "skip", 0)
    page = _page_from_skip(skip)

    if search:
        results = await db.search_documents(query=search, page=page, page_size=PAGE_SIZE)
        return [
            item for item in results.get("results", [])
            if _stremio_type(item) == content_type and _matches_genre(item, genre)
        ]

    source = catalog_definition["source"]

    if source == "sort":
        return await _sorted_items(content_type, catalog_definition["sort"], page, genre)

    if source == "editors":
        return await _editors_choice_items(content_type, page, genre)

    if source == "trending":
        return await _trending_items(content_type, skip, genre)

    if source == "kdrama":
        return await _collection_items(
            content_type,
            page,
            category="korean",
            sort_params=[("release_year", "desc"), ("updated_on", "desc"), ("rating", "desc")],
        )

    if source == "anime":
        return await _collection_items(
            content_type,
            page,
            category="anime",
            sort_params=[("release_year", "desc"), ("updated_on", "desc"), ("rating", "desc")],
        )

    if source == "language":
        return await _collection_items(
            content_type,
            page,
            genre=genre,
            language=catalog_definition.get("language"),
        )

    if source == "quality":
        return await _collection_items(
            content_type,
            page,
            genre=genre,
            quality=catalog_definition.get("quality"),
        )

    if source == "genre":
        return await _collection_items(
            content_type,
            page,
            genre=catalog_definition.get("genre") or genre,
            sort_params=[("rating", "desc"), ("updated_on", "desc")],
        )

    if source == "season_packs":
        return await _season_pack_items(page, genre)

    return []


async def _sorted_items(
    content_type: str,
    sort_params: List[Tuple[str, str]],
    page: int,
    genre: Optional[str],
) -> List[Dict[str, Any]]:
    if genre:
        return await _collection_items(content_type, page, genre=genre, sort_params=sort_params)

    genres = [genre] if genre else None
    if content_type == "movie":
        results = await db.sort_movies(sort_params, page=page, page_size=PAGE_SIZE, genres=genres)
    else:
        results = await db.sort_tv_shows(sort_params, page=page, page_size=PAGE_SIZE, genres=genres)
    return _clean_items(results.get(_result_key(content_type), []))


async def _editors_choice_items(content_type: str, page: int, genre: Optional[str]) -> List[Dict[str, Any]]:
    results = await db.get_editors_choice(
        media_type=_backend_media_type(content_type),
        page=page,
        page_size=PAGE_SIZE,
        min_rating=7.0,
        min_files=1,
    )
    return [item for item in results.get(_result_key(content_type), []) if _matches_genre(item, genre)]


async def _trending_items(content_type: str, skip: int, genre: Optional[str]) -> List[Dict[str, Any]]:
    results = await db.get_trending()
    items = [
        item for item in results.get("results", [])
        if _stremio_type(item) == content_type and _matches_genre(item, genre)
    ]
    return items[skip:skip + PAGE_SIZE]


async def _collection_items(
    content_type: str,
    page: int,
    genre: Optional[str] = None,
    language: Optional[Any] = None,
    quality: Optional[str] = None,
    category: Optional[str] = None,
    sort_params: Optional[List[Tuple[str, str]]] = None,
) -> List[Dict[str, Any]]:
    skip = (page - 1) * PAGE_SIZE
    collection = db.movie_collection if content_type == "movie" else db.tv_collection
    if collection is None:
        return []

    query: Dict[str, Any] = {}
    if category == "korean":
        query = _korean_content_query()
    elif category == "anime":
        query = _anime_content_query()
    if genre:
        query["genres"] = _exact_text_regex(genre)
    if language:
        if isinstance(language, (list, tuple, set)):
            language_options = [
                {"languages": _exact_text_regex(str(item))}
                for item in language
            ]
            query.setdefault("$and", []).append({"$or": language_options})
        else:
            query["languages"] = _exact_text_regex(str(language))
    if quality and content_type == "movie":
        query["telegram.quality"] = _quality_regex(quality)
    elif quality:
        quality_query = {"$or": [
            {"seasons.episodes.telegram.quality": _quality_regex(quality)},
            {"seasons.packs.telegram.quality": _quality_regex(quality)},
        ]}
        if "$and" in query:
            query["$and"].append(quality_query)
        else:
            query.update(quality_query)

    cursor = collection.find(query).sort(_mongo_sort(sort_params or [("updated_on", "desc"), ("rating", "desc")])).skip(skip).limit(PAGE_SIZE)
    return [db._convert_object_id(item) for item in await cursor.to_list(PAGE_SIZE)]


async def _season_pack_items(page: int, genre: Optional[str]) -> List[Dict[str, Any]]:
    skip = (page - 1) * PAGE_SIZE
    if db.tv_collection is None:
        return []

    query: Dict[str, Any] = {"seasons.packs.0": {"$exists": True}}
    if genre:
        query["genres"] = _exact_text_regex(genre)

    cursor = db.tv_collection.find(query).sort([("updated_on", -1), ("rating", -1)]).skip(skip).limit(PAGE_SIZE)
    return [db._convert_object_id(item) for item in await cursor.to_list(PAGE_SIZE)]


@router.get("/meta/{content_type}/{stremio_id}.json")
async def meta(content_type: str, stremio_id: str) -> Dict[str, Any]:
    if not await _authorized_stremio_user(None):
        return {"meta": None}
    return await _meta_response(content_type, stremio_id)


async def _meta_response(content_type: str, stremio_id: str) -> Dict[str, Any]:
    tmdb_id, _, _ = _parse_stremio_id(stremio_id)
    details = await db.get_media_details(tmdb_id=tmdb_id)
    if not details:
        raise HTTPException(status_code=404, detail="Media not found")

    resolved_type = _stremio_type(details)
    if content_type != resolved_type:
        return {"meta": None}

    return {"meta": _full_meta(details)}


@router.get("/{access_token}/meta/{content_type}/{stremio_id}.json")
async def authenticated_meta(access_token: str, content_type: str, stremio_id: str) -> Dict[str, Any]:
    if not await _authorized_stremio_user(access_token):
        return {"meta": None}
    return await _meta_response(content_type, stremio_id)


@router.get("/stream/{content_type}/{stremio_id}.json")
async def stream(request: Request, content_type: str, stremio_id: str) -> Dict[str, Any]:
    if not await _authorized_stremio_user(None):
        return {"streams": []}
    return await _stream_response(request, content_type, stremio_id)


async def _stream_response(request: Request, content_type: str, stremio_id: str) -> Dict[str, Any]:
    tmdb_id, season_number, episode_number = _parse_stremio_id(stremio_id)
    base_url = _absolute_base_url(request)

    if content_type == "movie":
        streams = await _movie_streams(base_url, tmdb_id)
    elif content_type == "series":
        streams = await _series_streams(base_url, tmdb_id, season_number, episode_number)
    else:
        streams = []

    return {"streams": streams}


@router.get("/{access_token}/stream/{content_type}/{stremio_id}.json")
async def authenticated_stream(request: Request, access_token: str, content_type: str, stremio_id: str) -> Dict[str, Any]:
    if not await _authorized_stremio_user(access_token):
        return {"streams": []}
    return await _stream_response(request, content_type, stremio_id)
