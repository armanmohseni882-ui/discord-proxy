import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from typing import List, Dict, Any

from src.utils.api_client import get_current_nba_season
from src.utils.exceptions import ApiError, StatsNotFoundException

STAT_CHOICES = [
    app_commands.Choice(name="Points", value="pts"),
    app_commands.Choice(name="Rebounds", value="reb"),
    app_commands.Choice(name="Assists", value="ast"),
    app_commands.Choice(name="Blocks", value="blk"),
    app_commands.Choice(name="Steals", value="stl"),
    app_commands.Choice(name="Turnovers", value="turnover"),
    app_commands.Choice(name="3-Pointers Made", value="fg3m"),
    app_commands.Choice(name="Points + Rebounds + Assists", value="pts+reb+ast"),
    app_commands.Choice(name="FG%", value="fg_pct"),
    app_commands.Choice(name="3P%", value="fg3_pct"),
    app_commands.Choice(name="FT%", value="ft_pct"),
]

class NBACog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def player_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        if not current: return []
        try:
            players = await self.bot.api_client.get_nba_players(search=current)
            if not players or not players.get("data"): return []

            choices = []
            for player in players["data"]:
                team = player.get('team', {}).get('abbreviation', 'N/A')
                name = f"{player['first_name']} {player['last_name']} ({team})"
                choices.append(app_commands.Choice(name=name, value=str(player['id'])))
                if len(choices) == 25: break
            return choices
        except ApiError:
            return []

    @app_commands.command(name="nbastats", description="Get a player's average stats over their last N games.")
    @app_commands.autocomplete(player=player_autocomplete)
    @app_commands.choices(stat=STAT_CHOICES)
    @app_commands.choices(games=[app_commands.Choice(name="Last 5 Games", value="5"), app_commands.Choice(name="Last 10 Games", value="10")])
    async def nbastats(self, interaction: discord.Interaction, player: str, stat: str, games: str):
        await interaction.response.defer(ephemeral=True)
        player_id = int(player)
        num_games = int(games)

        season = get_current_nba_season()
        game_logs = await self.bot.api_client.get_nba_player_stats_for_season(player_id, season)

        # If not enough games in current season, check previous
        if len(game_logs) < num_games:
            prev_season_logs = await self.bot.api_client.get_nba_player_stats_for_season(player_id, season - 1)
            game_logs.extend(prev_season_logs)

        # Sort by date and filter for games played
        played_games = sorted([g for g in game_logs if g.get('min')], key=lambda x: x['game']['date'], reverse=True)
        recent_games = played_games[:num_games]

        if not recent_games:
            raise StatsNotFoundException("Could not find recent game stats for this player.")

        avg_stat, stat_name, player_name = self._calculate_average_stat(recent_games, stat)

        embed = discord.Embed(
            title=f"{player_name} - {stat_name}",
            description=f"Average over the last {len(recent_games)} games played.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Average", value=f"**{avg_stat}**")
        await interaction.followup.send(embed=embed, ephemeral=True)

    def _calculate_average_stat(self, games: List[Dict[str, Any]], stat_key: str) -> (str, str, str):
        player_name = f"{games[0]['player']['first_name']} {games[0]['player']['last_name']}"
        stat_name = next((c.name for c in STAT_CHOICES if c.value == stat_key), stat_key)

        if stat_key.endswith('_pct'):
            made_key, attempted_key = {"fg_pct": ("fgm", "fga"), "fg3_pct": ("fg3m", "fg3a"), "ft_pct": ("ftm", "fta")}[stat_key]
            total_made = sum(g.get(made_key, 0) for g in games)
            total_attempted = sum(g.get(attempted_key, 0) for g in games)
            avg = (total_made / total_attempted * 100) if total_attempted > 0 else 0
            return f"{avg:.1f}%", stat_name, player_name

        if "+" in stat_key:
            keys = stat_key.split('+')
            total = sum(sum(g.get(k, 0) for k in keys) for g in games)
        else:
            total = sum(g.get(stat_key, 0) for g in games)

        avg = total / len(games)
        return f"{avg:.1f}", stat_name, player_name

    @app_commands.command(name="nbaseasonstats", description="Get a player's stats for the current season.")
    @app_commands.autocomplete(player=player_autocomplete)
    async def nbaseasonstats(self, interaction: discord.Interaction, player: str):
        await interaction.response.defer(ephemeral=True)
        player_id = int(player)
        season = get_current_nba_season()

        game_logs = await self.bot.api_client.get_nba_player_stats_for_season(player_id, season)
        if not game_logs:
            raise StatsNotFoundException(f"Could not find stats for this player in the {season} season.")

        stats = self._calculate_season_totals(game_logs)
        player_name = f"{game_logs[0]['player']['first_name']} {game_logs[0]['player']['last_name']}"

        embed = discord.Embed(title=f"{player_name} - {season} Season Averages", color=discord.Color.gold())
        embed.add_field(name="PPG", value=f"{stats['pts']:.1f}", inline=True)
        embed.add_field(name="RPG", value=f"{stats['reb']:.1f}", inline=True)
        embed.add_field(name="APG", value=f"{stats['ast']:.1f}", inline=True)
        embed.add_field(name="SPG", value=f"{stats['stl']:.1f}", inline=True)
        embed.add_field(name="BPG", value=f"{stats['blk']:.1f}", inline=True)
        embed.add_field(name="3PM", value=f"{stats['fg3m']:.1f}", inline=True)
        embed.add_field(name="FG%", value=f"{stats['fg_pct']:.1f}%", inline=True)
        embed.add_field(name="3P%", value=f"{stats['fg3_pct']:.1f}%", inline=True)
        embed.add_field(name="FT%", value=f"{stats['ft_pct']:.1f}%", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    def _calculate_season_totals(self, game_logs: List[Dict[str, Any]]) -> Dict[str, float]:
        games_played = len(game_logs)
        if games_played == 0: return {}

        totals = {k: sum(g.get(k, 0) for g in game_logs) for k in ["pts", "reb", "ast", "stl", "blk", "fg3m", "fgm", "fga", "fg3a", "ftm", "fta"]}

        return {
            "pts": totals["pts"] / games_played,
            "reb": totals["reb"] / games_played,
            "ast": totals["ast"] / games_played,
            "stl": totals["stl"] / games_played,
            "blk": totals["blk"] / games_played,
            "fg3m": totals["fg3m"] / games_played,
            "fg_pct": (totals["fgm"] / totals["fga"] * 100) if totals["fga"] > 0 else 0,
            "fg3_pct": (totals["fg3m"] / totals["fg3a"] * 100) if totals["fg3a"] > 0 else 0,
            "ft_pct": (totals["ftm"] / totals["fta"] * 100) if totals["fta"] > 0 else 0,
        }

    _leaderboard_cache = {}
    _LEADERBOARD_CACHE_TTL = 21600 # 6 hours

    @app_commands.command(name="nbaleagueleaders", description="NBA league leaders for the current season.")
    async def nbaleagueleaders(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        season = get_current_nba_season()

        # Check cache
        if season in self._leaderboard_cache and (discord.utils.utcnow() - self._leaderboard_cache[season]['timestamp']).total_seconds() < self._LEADERBOARD_CACHE_TTL:
            await interaction.followup.send(embed=self._leaderboard_cache[season]['embed'], ephemeral=True)
            return

        all_game_logs = await self.bot.api_client.get_all_nba_stats_for_season(season)
        if not all_game_logs:
            raise StatsNotFoundException("Could not retrieve league leader data.")

        # Process stats
        player_stats = {}
        for game in all_game_logs:
            p_id = game['player']['id']
            if p_id not in player_stats:
                player_stats[p_id] = {
                    "games_played": 0, "pts": 0, "reb": 0, "ast": 0, "stl": 0, "blk": 0,
                    "player_info": game['player']
                }
            player_stats[p_id]["games_played"] += 1
            for stat in ["pts", "reb", "ast", "stl", "blk"]:
                player_stats[p_id][stat] += game.get(stat, 0)

        # Calculate averages and filter
        min_games = 20 # Minimum games played to qualify for leaderboards
        qualified_players = [p for p in player_stats.values() if p["games_played"] >= min_games]
        for p in qualified_players:
            p["ppg"] = p["pts"] / p["games_played"]
            p["rpg"] = p["reb"] / p["games_played"]
            p["apg"] = p["ast"] / p["games_played"]
            p["spg"] = p["stl"] / p["games_played"]
            p["bpg"] = p["blk"] / p["games_played"]

        # Get leaders
        leaders = {
            "Points": sorted(qualified_players, key=lambda x: x["ppg"], reverse=True)[:5],
            "Rebounds": sorted(qualified_players, key=lambda x: x["rpg"], reverse=True)[:5],
            "Assists": sorted(qualified_players, key=lambda x: x["apg"], reverse=True)[:5],
            "Steals": sorted(qualified_players, key=lambda x: x["spg"], reverse=True)[:5],
            "Blocks": sorted(qualified_players, key=lambda x: x["bpg"], reverse=True)[:5],
        }

        # Create Embed
        embed = discord.Embed(title=f"NBA League Leaders - {season} Season", color=discord.Color.purple())
        for stat_name, player_list in leaders.items():
            leader_text = []
            for i, p_stat in enumerate(player_list):
                name = f"{p_stat['player_info']['first_name']} {p_stat['player_info']['last_name']}"
                avg_key = stat_name.lower()[:1] + "pg"
                value = p_stat.get(avg_key, 0)
                leader_text.append(f"**{i+1}.** {name} - `{value:.1f}`")
            embed.add_field(name=f"🏆 {stat_name}", value="\n".join(leader_text), inline=True)

        # Cache the result
        self._leaderboard_cache[season] = {"embed": embed, "timestamp": discord.utils.utcnow()}

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        original = getattr(error, 'original', error)
        if isinstance(original, (ApiError, StatsNotFoundException)):
            message = str(original) or "Sorry, I couldn't retrieve the stats right now."
            await interaction.followup.send(message, ephemeral=True)
        else:
            print(f"An unexpected error occurred in NBACog: {original}")
            await interaction.followup.send("An unexpected error occurred.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(NBACog(bot))
