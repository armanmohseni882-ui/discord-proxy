import os
import aiohttp
from async_lru import alru_cache
from datetime import datetime
from .exceptions import ApiError

class ApiClient:
    """
    An asynchronous client for interacting with the balldontlie API for NBA, NFL, and MLB.
    """
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("API key must be provided.")
        self._api_key = api_key
        self._session = None

        self.NBA_BASE = "https://api.balldontlie.io/v1"
        self.NFL_BASE = "https://api.balldontlie.io/nfl/v1"
        self.MLB_BASE = "https://api.balldontlie.io/mlb/v1"

    async def connect(self):
        self._session = aiohttp.ClientSession()

    async def close(self):
        if self._session:
            await self._session.close()

    async def _request(self, base_url: str, endpoint: str, params: dict = None):
        if not self._session:
            await self.connect()

        headers = {"Authorization": self._api_key}
        url = f"{base_url}{endpoint}"

        try:
            async with self._session.get(url, headers=headers, params=params) as response:
                if response.status == 404: return None
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientError as e:
            raise ApiError(f"API request to {url} failed: {e}") from e

    # --- NBA Methods ---
    @alru_cache(maxsize=1024, ttl=3600)
    async def get_nba_players(self, search: str):
        return await self._request(self.NBA_BASE, "/players", {"search": search})

    @alru_cache(maxsize=1024, ttl=86400)
    async def get_nba_player_stats_for_season(self, player_id: int, season: int):
        # This method is still needed for /nbastats (last N games)
        all_stats = []
        cursor = 0
        while True:
            params = {"seasons[]": [season], "player_ids[]": [player_id], "per_page": 100, "cursor": cursor}
            data = await self._request(self.NBA_BASE, "/stats", params)
            if not data or not data.get("data"): break
            all_stats.extend(data["data"])
            cursor = data.get("meta", {}).get("next_cursor")
            if not cursor: break
        return all_stats

    @alru_cache(maxsize=1024, ttl=43200)
    async def get_nba_season_averages(self, player_id: int, season: int):
        # GOAT-tier endpoint
        params = {"season": season, "player_ids[]": [player_id]}
        # The 'general' and 'base' types provide standard PPG, RPG, etc.
        return await self._request(self.NBA_BASE, "/season_averages/general", {**params, "season_type": "regular", "type": "base"})

    @alru_cache(maxsize=1024, ttl=21600)
    async def get_nba_leaders(self, season: int, stat_type: str):
        # GOAT-tier endpoint
        params = {"season": season, "stat_type": stat_type}
        return await self._request(self.NBA_BASE, "/leaders", params)

    # --- NFL Methods ---
    @alru_cache(maxsize=1024, ttl=3600)
    async def get_nfl_players(self, search: str):
        return await self._request(self.NFL_BASE, "/players", {"search": search})

    @alru_cache(maxsize=1024, ttl=43200)
    async def get_nfl_season_stats(self, player_id: int, season: int):
        params = {"season": season, "player_ids[]": [player_id]}
        return await self._request(self.NFL_BASE, "/season_stats", params)

    @alru_cache(maxsize=1024, ttl=21600)
    async def get_nfl_league_leaders(self, season: int, stat: str):
        params = {"season": season, "sort_by": stat, "sort_order": "desc"}
        return await self._request(self.NFL_BASE, "/season_stats", params)

    @alru_cache(maxsize=1024, ttl=86400)
    async def get_nfl_player_stats_for_season(self, player_id: int, season: int):
        params = {"season": season, "player_ids[]": [player_id]}
        return await self._request(self.NFL_BASE, "/stats", params)

    # --- MLB Methods ---
    @alru_cache(maxsize=1024, ttl=3600)
    async def get_mlb_players(self, search: str):
        return await self._request(self.MLB_BASE, "/players", {"search": search})

    @alru_cache(maxsize=1024, ttl=86400)
    async def get_mlb_player_stats_for_season(self, player_id: int, season: int):
        # This method is still needed for /mlbstats (last N games)
        all_stats = []
        cursor = 0
        while True:
            params = {"seasons[]": [season], "player_ids[]": [player_id], "per_page": 100, "cursor": cursor}
            data = await self._request(self.MLB_BASE, "/stats", params)
            if not data or not data.get("data"): break
            all_stats.extend(data["data"])
            cursor = data.get("meta", {}).get("next_cursor")
            if not cursor: break
        return all_stats

    @alru_cache(maxsize=1024, ttl=43200)
    async def get_mlb_season_stats(self, player_id: int, season: int):
        # GOAT-tier endpoint
        params = {"season": season, "player_ids[]": [player_id]}
        return await self._request(self.MLB_BASE, "/season_stats", params)

    @alru_cache(maxsize=1024, ttl=21600)
    async def get_mlb_league_leaders(self, season: int, stat: str):
        # GOAT-tier endpoint with sorting
        params = {"season": season, "sort_by": stat, "sort_order": "desc"}
        return await self._request(self.MLB_BASE, "/season_stats", params)

# --- Season Helper Functions ---
def get_current_nba_season() -> int:
    now = datetime.now()
    return now.year if now.month >= 10 else now.year - 1

def get_current_nfl_season() -> int:
    now = datetime.now()
    return now.year if now.month >= 9 else now.year - 1

def get_current_mlb_season() -> int:
    now = datetime.now()
    return now.year if now.month >= 4 else now.year - 1
