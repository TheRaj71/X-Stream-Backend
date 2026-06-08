from datetime import datetime
from pydantic import BaseModel, Field, ValidationError
from typing import Dict, List, Optional

class QualityDetail(BaseModel):
    quality: str = Field(..., description="Quality of the video (e.g., 1080p, 720p)")
    id: str = Field(..., description="Unique hash for the video")
    name: str = Field(..., description="Original Filename of telegram file")
    size: str = Field(..., description="Size of the File")

class Episode(BaseModel):
    episode_number: int = Field(..., description="Episode number within the season")
    title: str = Field(..., description="Title of the episode")
    episode_backdrop: str = Field(..., description="Backdrop of Episode")
    telegram: Optional[List[QualityDetail]] = Field(None, description="List of available quality details")

class Season(BaseModel):
    season_number: int = Field(..., description="Season number within the TV show")
    episodes: List[Episode] = Field(..., description="List of episodes in the season")

class TVShowSchema(BaseModel):
    tmdb_id: int = Field(..., description="The TMDB ID of the TV show")
    title: str = Field(..., description="Title of the TV show")
    genres: List[str] = Field(..., description="List of genres associated with the TV show")
    description: str = Field(..., description="Brief description of the TV show")
    rating: float = Field(..., description="Average rating of the TV show")
    vote_count: int = Field(default=0, description="Number of votes for the TV show")
    popularity: float = Field(default=0, description="Popularity score for the TV show")
    release_year: int = Field(..., description="Release year of the TV show")
    poster: str = Field(..., description="URL to the poster image")
    backdrop: str = Field(..., description="URL to the backdrop image")
    trailer_url: Optional[str] = Field(default=None, description="YouTube trailer embed URL")
    cast: List[Dict] = Field(default_factory=list, description="Primary cast")
    total_seasons: int = Field(..., description="Total Season of tv show")
    total_episodes: int = Field(..., description="Total Episode of tv show")
    media_type: str = Field(..., description="Media Type of the file")
    status: str = Field(..., description="Status update of tv show")
    updated_on: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of the last update")
    languages: List[str] = Field(..., description="List of languages associated with the Movie")
    rip: str = Field(..., description="Media rip of the file")
    seasons: List[Season] = Field(..., description="List of seasons in the TV show")



class MovieSchema(BaseModel):
    tmdb_id: int = Field(..., description="The TMDB ID of the Movie")
    title: str = Field(..., description="Title of the Movie")
    genres: List[str] = Field(..., description="List of genres associated with the Movie")
    description: str = Field(..., description="Brief description of the Movie")
    rating: float = Field(..., description="Average rating of the Movie")
    vote_count: int = Field(default=0, description="Number of votes for the movie")
    popularity: float = Field(default=0, description="Popularity score for the movie")
    release_year: int = Field(..., description="Release year of the Movie")
    poster: str = Field(..., description="URL to the poster image")
    backdrop: str = Field(..., description="URL to the backdrop image")
    trailer_url: Optional[str] = Field(default=None, description="YouTube trailer embed URL")
    cast: List[Dict] = Field(default_factory=list, description="Primary cast")
    media_type: str = Field(..., description="Media Type of the file")
    runtime: int = Field(..., description="runtime of the movie")
    updated_on: datetime = Field(default_factory=datetime.utcnow, description="Timestamp of the last update")
    languages: List[str] = Field(..., description="List of languages associated with the Movie")
    rip: str = Field(..., description="Media rip of the file")
    telegram: Optional[List[QualityDetail]] = Field(None, description="List of available quality details")
