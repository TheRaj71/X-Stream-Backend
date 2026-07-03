from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, unquote_plus

from fastapi import APIRouter, HTTPException, Request

from Backend import __version__, db
from Backend.config import Telegram


router = APIRouter(prefix="/stremio", tags=["stremio-addon"])

ADDON_ID = "org.xstream.backend"
ADDON_NAME = "X-Stream"
CATALOG_MOVIES = "xstream-movies"
CATALOG_SERIES = "xstream-series"


def _as_dict(value: Any) -> Dict[str, Any]:
    if hasattr(value, "dict"):
        return value.dict()
    return dict(value or {})


def _absolute_base_url(request: Request) -> str:
    configured_url = Telegram.BASE_URL
    if configured_url and configured_url not in ("0.0.0.0", "127.0.0.1", "localhost"):
        return configured_url.rstrip("/")
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


def _preview_meta(document: Dict[str, Any]) -> Dict[str, Any]:
    media_type = _stremio_type(document)
    return {
        "id": f"tmdb:{document.get('tmdb_id')}",
        "type": media_type,
        "name": document.get("title", "Untitled"),
        "poster": document.get("poster"),
        "background": document.get("backdrop"),
        "description": document.get("description"),
        "releaseInfo": str(document.get("release_year") or ""),
        "imdbRating": str(document.get("rating") or ""),
        "genres": document.get("genres") or [],
    }


def _full_meta(document: Dict[str, Any]) -> Dict[str, Any]:
    meta = _preview_meta(document)
    meta.update({
        "runtime": document.get("runtime"),
        "trailers": _trailers(document.get("trailer_url")),
    })

    if meta["type"] == "series":
        meta["videos"] = _series_videos(document)

    return {key: value for key, value in meta.items() if value not in (None, "", [])}


def _trailers(trailer_url: Optional[str]) -> List[Dict[str, str]]:
    if not trailer_url:
        return []
    return [{"source": trailer_url, "type": "Trailer"}]


def _series_videos(document: Dict[str, Any]) -> List[Dict[str, Any]]:
    videos: List[Dict[str, Any]] = []
    tmdb_id = document.get("tmdb_id")

    for season in document.get("seasons") or []:
        season_number = season.get("season_number")
        for episode in season.get("episodes") or []:
            episode_number = episode.get("episode_number")
            if season_number is None or episode_number is None:
                continue
            videos.append({
                "id": f"tmdb:{tmdb_id}:{season_number}:{episode_number}",
                "title": episode.get("title") or f"Episode {episode_number}",
                "season": season_number,
                "episode": episode_number,
                "thumbnail": episode.get("episode_backdrop") or document.get("backdrop"),
            })

    return sorted(videos, key=lambda item: (item.get("season", 0), item.get("episode", 0)))


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
            numbers = pack.get("episode_numbers") or []
            start = pack.get("episode_start")
            end = pack.get("episode_end")
            contains_episode = episode_number in numbers or (
                start is not None and end is not None and start <= episode_number <= end
            )
            if contains_episode:
                streams.extend(_stream_items(base_url, pack.get("telegram") or [], prefix=pack.get("title") or "Pack"))
    else:
        streams.extend(_stream_items(base_url, season.get("packs") or [], prefix=f"S{season_number} Pack"))

    return streams


@router.get("/manifest.json")
async def manifest() -> Dict[str, Any]:
    return {
        "id": ADDON_ID,
        "version": __version__,
        "name": ADDON_NAME,
        "description": "Stream your X-Stream backend library in Stremio-compatible clients.",
        "resources": ["catalog", "meta", "stream"],
        "types": ["movie", "series"],
        "catalogs": [
            {
                "type": "movie",
                "id": CATALOG_MOVIES,
                "name": "X-Stream Movies",
                "extra": [{"name": "search", "isRequired": False}],
            },
            {
                "type": "series",
                "id": CATALOG_SERIES,
                "name": "X-Stream Series",
                "extra": [{"name": "search", "isRequired": False}],
            },
        ],
        "idPrefixes": ["tmdb:"],
        "behaviorHints": {"configurable": False},
    }


@router.get("/catalog/{content_type}/{catalog_id}.json")
@router.get("/catalog/{content_type}/{catalog_id}/{extra}.json")
async def catalog(content_type: str, catalog_id: str, extra: Optional[str] = None) -> Dict[str, Any]:
    params = _parse_extra(extra)
    search = params.get("search")

    if content_type not in ("movie", "series"):
        return {"metas": []}

    if search:
        results = await db.search_documents(query=search, page=1, page_size=50)
        metas = [
            _preview_meta(item)
            for item in results.get("results", [])
            if _stremio_type(item) == content_type
        ]
        return {"metas": metas}

    if content_type == "movie" and catalog_id == CATALOG_MOVIES:
        results = await db.sort_movies([("updated_on", "desc")], page=1, page_size=50)
        return {"metas": [_preview_meta(item) for item in _clean_items(results.get("movies", []))]}

    if content_type == "series" and catalog_id == CATALOG_SERIES:
        results = await db.sort_tv_shows([("updated_on", "desc")], page=1, page_size=50)
        return {"metas": [_preview_meta(item) for item in _clean_items(results.get("tv_shows", []))]}

    return {"metas": []}


@router.get("/meta/{content_type}/{stremio_id}.json")
async def meta(content_type: str, stremio_id: str) -> Dict[str, Any]:
    tmdb_id, _, _ = _parse_stremio_id(stremio_id)
    details = await db.get_media_details(tmdb_id=tmdb_id)
    if not details:
        raise HTTPException(status_code=404, detail="Media not found")

    resolved_type = _stremio_type(details)
    if content_type != resolved_type:
        return {"meta": None}

    return {"meta": _full_meta(details)}


@router.get("/stream/{content_type}/{stremio_id}.json")
async def stream(request: Request, content_type: str, stremio_id: str) -> Dict[str, Any]:
    tmdb_id, season_number, episode_number = _parse_stremio_id(stremio_id)
    base_url = _absolute_base_url(request)

    if content_type == "movie":
        streams = await _movie_streams(base_url, tmdb_id)
    elif content_type == "series":
        streams = await _series_streams(base_url, tmdb_id, season_number, episode_number)
    else:
        streams = []

    return {"streams": streams}
