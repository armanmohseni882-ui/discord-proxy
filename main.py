"""
Discord Sports Bot using MySportsFeeds API

This bot provides live sports scores, player projections, and prop bet alerts
for a premium Discord community.

Instructions for Replit Setup:
1. Copy this entire script into the `main.py` file of your Python Replit project.
2. Create a `requirements.txt` file and add `discord.py` and `aiohttp`.
3. In the Replit sidebar, go to the "Secrets" tab.
4. Add the following secrets:
   - DISCORD_TOKEN: Your Discord bot's token.
   - MYSPORTSFEEDS_API_KEY: Your MySportsFeeds API key.
   - ALERT_CHANNEL_ID: The ID of the channel where prop bet alerts should be sent.
   - SCOREBOARD_NFL_CHANNEL_ID: The ID of the channel for the NFL scoreboard.
   - SCOREBOARD_NBA_CHANNEL_ID: The ID of the channel for the NBA scoreboard.
   - SCOREBOARD_MLB_CHANNEL_ID: The ID of the channel for the MLB scoreboard.
5. Click the "Run" button.
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands

import os
import aiohttp
import asyncio
from datetime import datetime, timedelta
import base64
import logging
from typing import List, Dict, Any, Optional

# --- Basic Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Environment & Secrets ---
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
MYSPORTSFEEDS_API_KEY = os.environ.get("MYSPORTSFEEDS_API_KEY")
ALERT_CHANNEL_ID = int(os.environ.get("ALERT_CHANNEL_ID", 0))
SCOREBOARD_CHANNEL_IDS = {
    "nfl": int(os.environ.get("SCOREBOARD_NFL_CHANNEL_ID", 0)),
    "nba": int(os.environ.get("SCOREBOARD_NBA_CHANNEL_ID", 0)),
    "mlb": int(os.environ.get("SCOREBOARD_MLB_CHANNEL_ID", 0)),
}

if not all([DISCORD_TOKEN, MYSPORTSFEEDS_API_KEY, ALERT_CHANNEL_ID] + list(SCOREBOARD_CHANNEL_IDS.values())):
    logging.error("FATAL: One or more environment variables are not set. Please configure them in Replit Secrets.")
    exit()

# --- Constants ---
LEAGUES = ["nfl", "nba", "mlb"]
NFL_POSITIONS = ["QB", "RB", "WR", "TE", "K"]
PROP_ALERT_THRESHOLD = 0.8
API_BASE_URL = "https://api.mysportsfeeds.com/v2.1/pull"
PLAYER_CACHE_TTL = timedelta(hours=6)
PROJECTION_CACHE_TTL = timedelta(hours=24)

PROP_STATS_TO_TRACK = {
    "nfl": ["passingYards", "passingTouchdowns", "rushingYards", "rushingTouchdowns", "receivingYards", "receivingTouchdowns"],
    "nba": ["points", "rebounds", "assists"],
    "mlb": [],
}

# --- API Client ---
class MySportsFeedsClient:
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("API key cannot be empty.")
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Basic {base64.b64encode(f'{self.api_key}:MYSPORTSFEEDS'.encode('utf-8')).decode('ascii')}"
        }
        self.session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(headers=self.headers)
        return self.session

    async def close_session(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def _make_request(self, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        session = await self._get_session()
        try:
            async with session.get(url, params=params) as response:
                if response.status == 200:
                    return await response.json()
                elif response.status == 429:
                    logging.warning("API rate limit hit. Waiting 60 seconds.")
                    await asyncio.sleep(60)
                    return await self._make_request(url, params)
                else:
                    logging.error(f"API Error {response.status} for {url}: {await response.text()}")
                    return None
        except aiohttp.ClientError as e:
            logging.error(f"AIOHTTP client error for {url}: {e}")
            return None

    async def get_daily_games(self, league: str) -> Optional[Dict[str, Any]]:
        today = datetime.now().strftime('%Y%m%d')
        url = f"{API_BASE_URL}/{league}/latest/games.json"
        params = {"date": today}
        return await self._make_request(url, params)

    async def get_game_boxscore(self, league: str, game_id: int) -> Optional[Dict[str, Any]]:
        url = f"{API_BASE_URL}/{league}/latest/games/{game_id}/boxscore.json"
        return await self._make_request(url)

    async def get_player_projections(self, league: str, season: str = "latest") -> Optional[Dict[str, Any]]:
        url = f"{API_BASE_URL}/{league}/{season}/player_projections.json"
        return await self._make_request(url)

    async def get_active_players(self, league: str) -> Optional[Dict[str, Any]]:
        url = f"{API_BASE_URL}/{league}/players.json"
        return await self._make_request(url)

# --- Bot Core ---
class SportsBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)
        self.api_client = MySportsFeedsClient(MYSPORTSFEEDS_API_KEY)

        # Refactored State Management
        self.live_games_state: Dict[str, Dict[int, Dict[str, Any]]] = {"nfl": {}, "nba": {}, "mlb": {}}
        self.scoreboard_messages: Dict[str, Optional[int]] = {"nfl": None, "nba": None, "mlb": None}

        # Caching
        self.projections_cache: Dict[str, Dict[str, Any]] = {"nfl": {}, "nba": {}, "mlb": {}}
        self.player_cache: Dict[str, Dict[str, Any]] = {"nfl": {}, "nba": {}, "mlb": {}}

    async def setup_hook(self):
        logging.info("Starting setup hook...")
        self.cache_updater_task.start()
        self.live_game_updater.start()
        await self.tree.sync()
        logging.info("Bot is ready and commands are synced.")

    async def on_ready(self):
        logging.info(f'Logged in as {self.user} (ID: {self.user.id})')

    async def on_close(self):
        await self.api_client.close_session()
        logging.info("Bot shutting down.")

    # --- Caching Tasks ---
    @tasks.loop(hours=12)
    async def cache_updater_task(self):
        logging.info("Running scheduled cache update...")
        for league in LEAGUES:
            await self.update_player_cache(league, force=True)
            await self.update_projections_cache(league, force=True)
        logging.info("Scheduled cache update finished.")

    async def update_player_cache(self, league: str, force: bool = False):
        now = datetime.now()
        cache_info = self.player_cache[league]
        if not force and cache_info and (now - cache_info.get("timestamp", datetime.min)) < PLAYER_CACHE_TTL:
            return

        logging.info(f"Updating player cache for {league.upper()}...")
        data = await self.api_client.get_active_players(league)
        if data and "players" in data:
            player_list = []
            if league == "nfl":
                for p_ref in data.get("playerReferences", []):
                    if p_ref.get("player", {}).get("primaryPosition") in NFL_POSITIONS:
                        player_list.append(p_ref["player"])
            else:
                player_list = [p_ref["player"] for p_ref in data.get("playerReferences", [])]

            self.player_cache[league] = {"timestamp": now, "data": player_list}
            logging.info(f"Player cache for {league.upper()} updated with {len(player_list)} players.")

    async def update_projections_cache(self, league: str, force: bool = False):
        now = datetime.now()
        cache_info = self.projections_cache[league]
        if not force and cache_info and (now - cache_info.get("timestamp", datetime.min)) < PROJECTION_CACHE_TTL:
            return

        logging.info(f"Updating projections cache for {league.upper()}...")
        data = await self.api_client.get_player_projections(league)
        if data and "playerProjections" in data:
            self.projections_cache[league] = {"timestamp": now, "data": data}
            logging.info(f"Projections cache for {league.upper()} updated.")

    # --- Live Game Loop ---
    @tasks.loop(minutes=1)
    async def live_game_updater(self):
        logging.info("Running live game update task...")
        for league in LEAGUES:
            try:
                await self.update_league_scores(league)
            except Exception as e:
                logging.error(f"Error updating scores for {league}: {e}", exc_info=True)

    @live_game_updater.before_loop
    @cache_updater_task.before_loop
    async def before_tasks(self):
        await self.wait_until_ready()
        logging.info("Tasks are waiting for bot to be ready...")

    # --- Scoreboard & State Logic ---
    async def update_league_scores(self, league: str):
        channel = self.get_channel(SCOREBOARD_CHANNEL_IDS.get(league, 0))
        if not channel: return

        game_data = await self.api_client.get_daily_games(league)
        if not game_data or "games" not in game_data:
            await self.update_scoreboard_embed(league, channel, [], None) # Clear scoreboard
            return

        all_games = game_data.get("games", [])
        references = game_data.get("references", {})
        live_games = [g for g in all_games if g["schedule"]["playedStatus"] == "LIVE"]
        completed_games = [g for g in all_games if g["schedule"]["playedStatus"] == "COMPLETED"]

        # Process games that just finished
        state_game_ids = set(self.live_games_state[league].keys())
        for game in completed_games:
            game_id = game["schedule"]["id"]
            if game_id in state_game_ids:
                await self.post_final_score(league, game_id, channel)
                del self.live_games_state[league][game_id]
                logging.info(f"Game {game_id} ({league}) finished and removed from state.")

        # Update scoreboard
        await self.update_scoreboard_embed(league, channel, live_games, references)

        # Prop Hunter Logic
        for game in live_games:
            game_id = game["schedule"]["id"]
            if game_id not in self.live_games_state[league]:
                self.live_games_state[league][game_id] = {"alerts_sent": []}
                logging.info(f"New live game added to state: {game_id} ({league})")

            boxscore = await self.api_client.get_game_boxscore(league, game_id)
            if boxscore:
                await self.check_prop_bet_alerts(league, game_id, boxscore)

    async def update_scoreboard_embed(self, league, channel, live_games, references):
        embed = self.create_scoreboard_embed(league, live_games, references)
        message_id = self.scoreboard_messages[league]
        try:
            if message_id:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed)
            else:
                message = await channel.send(embed=embed)
                self.scoreboard_messages[league] = message.id
        except discord.NotFound:
            message = await channel.send(embed=embed)
            self.scoreboard_messages[league] = message.id
        except Exception as e:
            logging.error(f"Failed to update scoreboard for {league}: {e}")

    async def post_final_score(self, league: str, game_id: int, channel: discord.TextChannel):
        boxscore = await self.api_client.get_game_boxscore(league, game_id)
        if not boxscore: return

        game = boxscore["game"]
        home_team = game["homeTeam"]["abbreviation"]
        away_team = game["awayTeam"]["abbreviation"]
        home_score = boxscore.get("scoring", {}).get("homeScoreTotal", "N/A")
        away_score = boxscore.get("scoring", {}).get("awayScoreTotal", "N/A")

        embed = discord.Embed(
            title=f"FINAL: {away_team} @ {home_team}",
            description=f"**{away_team}** {away_score} - **{home_team}** {home_score}",
            color=discord.Color.dark_gold()
        )
        await channel.send(embed=embed)
        logging.info(f"Posted final score for {league} game {game_id}.")

    async def check_prop_bet_alerts(self, league: str, game_id: int, boxscore: Dict[str, Any]):
        alert_channel = self.get_channel(ALERT_CHANNEL_ID)
        projections_cache = self.projections_cache[league].get("data")
        if not alert_channel or not projections_cache or not PROP_STATS_TO_TRACK[league]:
            return

        all_live_players = boxscore.get("stats", {}).get("away", {}).get("players", []) + \
                           boxscore.get("stats", {}).get("home", {}).get("players", [])

        for player_stats in all_live_players:
            player_id = player_stats.get("player", {}).get("id")
            if not player_id: continue

            player_proj_data = next((p for p in projections_cache["playerProjections"] if p.get("player", {}).get("id") == player_id), None)
            if not player_proj_data: continue

            for stat_key in PROP_STATS_TO_TRACK[league]:
                # Simplified stat lookup, may need adjustment based on API response structure
                live_value = 0
                for stats_cat in player_stats.get("playerStats", []):
                    if stat_key in stats_cat.get("miscellaneous", {}):
                         live_value = stats_cat["miscellaneous"][stat_key]
                         break

                proj_item = next((p for p in player_proj_data.get("projections", []) if p["category"].replace(" ", "") == stat_key.replace(" ", "")), None)
                if not proj_item: continue

                proj_value = float(proj_item.get("amount", 0))

                if proj_value > 0 and live_value >= (proj_value * PROP_ALERT_THRESHOLD):
                    alert_id = f"{player_id}-{stat_key}"
                    if alert_id not in self.live_games_state[league][game_id]["alerts_sent"]:
                        player_name = f"{player_stats['player']['firstName']} {player_stats['player']['lastName']}"
                        embed = discord.Embed(
                            title=f"📈 Prop Bet Alert: {league.upper()}",
                            description=f"**{player_name}** is approaching their projected stats!",
                            color=discord.Color.green()
                        )
                        embed.add_field(name="Stat", value=proj_item['category'], inline=True)
                        embed.add_field(name="Progress", value=f"{live_value} / {proj_value} ({live_value/proj_value:.0%})", inline=True)
                        await alert_channel.send(embed=embed)
                        self.live_games_state[league][game_id]["alerts_sent"].append(alert_id)
                        logging.info(f"Sent prop alert for {player_name} for {stat_key}.")

    # --- Embed & UI Helpers ---
    def create_scoreboard_embed(self, league: str, live_games: List[Dict], references: Optional[Dict]) -> discord.Embed:
        embed = discord.Embed(
            title=f"🏆 Live {league.upper()} Scoreboard",
            description=f"Last updated: <t:{int(datetime.now().timestamp())}:R>",
            color=discord.Color.blue()
        )
        if not live_games:
            embed.description += "\n\nNo games are currently live."
            return embed

        team_refs = {t["id"]: t for t in references.get("teamReferences", [])} if references else {}
        for game in sorted(live_games, key=lambda g: g["schedule"].get("startTime", "")):
            schedule, score = game["schedule"], game["score"]
            home_team = team_refs.get(schedule["homeTeam"]["id"], {"abbreviation": "HOME"})
            away_team = team_refs.get(schedule["awayTeam"]["id"], {"abbreviation": "AWAY"})

            progress_bar, period_info = self.create_progress_bar(league, score)
            value = (
                f"**{away_team['abbreviation']}**: {score.get('awayScoreTotal', 0)} | "
                f"**{home_team['abbreviation']}**: {score.get('homeScoreTotal', 0)}\n"
                f"`{progress_bar}` {period_info}"
            )
            embed.add_field(name=f"{away_team['abbreviation']} @ {home_team['abbreviation']}", value=value, inline=False)
        return embed

    def create_progress_bar(self, league: str, score: Dict) -> (str, str):
        bar, info = "░" * 15, "Starting Soon"
        try:
            if league in ["nfl", "nba"]:
                total_q_secs = (15 if league == 'nfl' else 12) * 60
                q = score.get("currentQuarter", 0)
                if q == 0: return bar, info
                secs_left = score.get("secondsRemaining", 0)
                elapsed_in_q = total_q_secs - secs_left
                total_elapsed = ((q - 1) * total_q_secs) + elapsed_in_q
                total_game_secs = 4 * total_q_secs
                percent = min(total_elapsed / total_game_secs, 1.0)
                info = f"Q{q} - {secs_left // 60}:{secs_left % 60:02d}"
            elif league == "mlb":
                inning = score.get("currentInning", 0)
                if inning == 0: return bar, info
                percent = min((inning - 1) / 9.0, 1.0)
                info = f"{score.get('currentInningHalf', 'Top')} {inning}"

            filled_len = int(15 * percent)
            bar = "█" * filled_len + "░" * (15 - filled_len)
        except (KeyError, TypeError):
            pass # Keep default values
        return f"({bar})", info

# --- Bot Initialization ---
bot = SportsBot()

# --- Autocomplete Handlers ---
async def player_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
    league = interaction.data.get("options", [{}])[0].get("value") # Risky, depends on command structure
    if not league: # Fallback for playerprop
        for opt in interaction.data.get("options", []):
            if opt['name'] == 'league':
                league = opt['value']

    if not league: return []

    await bot.update_player_cache(league)
    players = bot.player_cache[league].get("data", [])

    choices = []
    for player in players:
        full_name = f"{player.get('firstName', '')} {player.get('lastName', '')}".strip()
        if current.lower() in full_name.lower():
            choices.append(app_commands.Choice(name=full_name, value=str(player["id"])))
        if len(choices) >= 25: break
    return choices

# --- Slash Commands ---
@bot.tree.command(name="projections", description="Get player projections for the week.")
@app_commands.describe(league="The league to get projections for.", player="The name of the player.")
@app_commands.rename(player='player_id')
@app_commands.autocomplete(player_id=player_autocomplete)
async def projections(interaction: discord.Interaction, league: str, player_id: str):
    await interaction.response.defer()
    await bot.update_projections_cache(league)
    projections_data = bot.projections_cache[league].get("data")

    if not projections_data:
        await interaction.followup.send("Projections data is not available at the moment.", ephemeral=True)
        return

    player_proj = next((p for p in projections_data["playerProjections"] if str(p.get("player", {}).get("id")) == player_id), None)
    if not player_proj:
        await interaction.followup.send("Could not find projections for the selected player.", ephemeral=True)
        return

    player_info = player_proj["player"]
    embed = discord.Embed(
        title=f"📊 {league.upper()} Projections for {player_info['firstName']} {player_info['lastName']}",
        description=f"**Position:** {player_info.get('primaryPosition', 'N/A')} | **Team:** {player_info.get('currentTeam', {}).get('abbreviation', 'N/A')}",
        color=discord.Color.purple()
    )
    for proj in player_proj.get("projections", []):
        embed.add_field(name=proj.get("category", "Stat"), value=str(proj.get("amount", "N/A")), inline=True)

    await interaction.followup.send(embed=embed)

@bot.tree.command(name="playerprop", description="Compare a player's projections vs. live stats.")
@app_commands.describe(league="The league of the player.", player="The name of the player to look up.")
@app_commands.rename(player='player_id')
@app_commands.choices(league=[
    app_commands.Choice(name="NFL", value="nfl"),
    app_commands.Choice(name="NBA", value="nba"),
    app_commands.Choice(name="MLB", value="mlb"),
])
@app_commands.autocomplete(player_id=player_autocomplete)
async def playerprop(interaction: discord.Interaction, league: app_commands.Choice[str], player_id: str):
    await interaction.response.defer()

    # 1. Find the player's live game
    game_data = await bot.api_client.get_daily_games(league.value)
    live_games = [g for g in game_data.get("games", []) if g["schedule"]["playedStatus"] == "LIVE"] if game_data else []

    player_boxscore = None
    player_id_int = int(player_id)

    for game in live_games:
        boxscore = await bot.api_client.get_game_boxscore(league.value, game["schedule"]["id"])
        if not boxscore: continue

        all_players = boxscore.get("stats", {}).get("away", {}).get("players", []) + boxscore.get("stats", {}).get("home", {}).get("players", [])
        for p_stats in all_players:
            if p_stats.get("player", {}).get("id") == player_id_int:
                player_boxscore = p_stats
                break
        if player_boxscore: break

    if not player_boxscore:
        await interaction.followup.send("Player is not in a currently live game or could not be found.", ephemeral=True)
        return

    # 2. Get projections
    await bot.update_projections_cache(league.value)
    projections_data = bot.projections_cache[league.value].get("data")
    player_proj = next((p for p in projections_data["playerProjections"] if p.get("player", {}).get("id") == player_id_int), None) if projections_data else None

    if not player_proj:
        await interaction.followup.send("Could not find projections for this player.", ephemeral=True)
        return

    # 3. Build Embed
    player_info = player_proj["player"]
    embed = discord.Embed(
        title=f"Live Prop Tracker: {player_info['firstName']} {player_info['lastName']}",
        description="Comparing pre-game projections to live performance.",
        color=discord.Color.orange()
    )

    body = ""
    for proj_item in player_proj.get("projections", []):
        stat_name_cat = proj_item["category"]
        stat_name_api = stat_name_cat[0].lower() + stat_name_cat[1:].replace(" ", "")

        live_val = 0
        for stats_cat in player_boxscore.get("playerStats", []):
             if stat_name_api in stats_cat.get("miscellaneous", {}):
                 live_val = stats_cat["miscellaneous"][stat_name_api]
                 break

        proj_val = proj_item["amount"]
        emoji = "⚪"
        if float(proj_val) > 0:
            ratio = live_val / float(proj_val)
            if ratio >= 1.0: emoji = "✅"
            elif ratio >= PROP_ALERT_THRESHOLD: emoji = "📈"
            elif ratio >= 0.5: emoji = "▶️"
        body += f"{emoji} **{stat_name_cat}**\n- Live: `{live_val}` | Projected: `{proj_val}`\n"

    embed.add_field(name="Stats Breakdown", value=body if body else "No comparable stats found.", inline=False)
    await interaction.followup.send(embed=embed)

# --- Entry Point ---
if __name__ == "__main__":
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)
    else:
        logging.critical("DISCORD_TOKEN not found in environment variables!")
