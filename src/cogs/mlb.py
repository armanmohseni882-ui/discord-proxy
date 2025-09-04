import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from typing import List, Dict, Any

from src.utils.api_client import get_current_mlb_season
from src.utils.exceptions import ApiError, StatsNotFoundException

MLB_STAT_CHOICES = [
    app_commands.Choice(name="Hits", value="hits"),
    app_commands.Choice(name="Home Runs", value="hr"),
    app_commands.Choice(name="RBIs", value="rbi"),
    app_commands.Choice(name="Runs", value="runs"),
    app_commands.Choice(name="Stolen Bases", value="sb"),
    app_commands.Choice(name="Strikeouts (Pitching)", value="p_k"),
    app_commands.Choice(name="Wins", value="wins"),
    app_commands.Choice(name="Saves", value="sv"),
    app_commands.Choice(name="ERA", value="era"),
]

class MLBCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._leaderboard_cache = {}
        self._LEADERBOARD_CACHE_TTL = 21600 # 6 hours

    async def player_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        if not current: return []
        try:
            players = await self.bot.api_client.get_mlb_players(search=current)
            if not players or not players.get("data"): return []

            choices = []
            for player in players["data"]:
                team = player.get('team', {}).get('abbreviation', 'N/A')
                pos = player.get('position', 'N/A')
                name = f"{player['full_name']} ({team}) - {pos}"
                choices.append(app_commands.Choice(name=name, value=str(player['id'])))
                if len(choices) == 25: break
            return choices
        except ApiError:
            return []

    @app_commands.command(name="mlbstats", description="Get a player's average stats over their last N games.")
    @app_commands.autocomplete(player=player_autocomplete)
    @app_commands.choices(stat=MLB_STAT_CHOICES)
    @app_commands.choices(games=[app_commands.Choice(name="Last 5 Games", value="5"), app_commands.Choice(name="Last 10 Games", value="10")])
    async def mlbstats(self, interaction: discord.Interaction, player: str, stat: str, games: str):
        await interaction.response.defer(ephemeral=True)
        player_id, num_games = int(player), int(games)

        season = get_current_mlb_season()
        game_logs = await self.bot.api_client.get_mlb_player_stats_for_season(player_id, season)

        if len(game_logs) < num_games:
            prev_season_logs = await self.bot.api_client.get_mlb_player_stats_for_season(player_id, season - 1)
            game_logs.extend(prev_season_logs)

        sorted_games = sorted(game_logs, key=lambda x: x['game']['date'], reverse=True)
        recent_games = sorted_games[:num_games]

        if not recent_games:
            raise StatsNotFoundException("Could not find recent game stats for this player.")

        total = sum(g.get(stat, 0) or 0 for g in recent_games)
        avg = total / len(recent_games)

        stat_name = next((c.name for c in MLB_STAT_CHOICES if c.value == stat), stat)
        player_name = recent_games[0]['player']['full_name']

        embed = discord.Embed(title=f"{player_name} - {stat_name}", description=f"Average over the last {len(recent_games)} games.", color=discord.Color.dark_blue())
        embed.add_field(name="Average", value=f"**{avg:.1f}**")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="mlbseasonstats", description="Get a player's season stats (hitter or pitcher).")
    @app_commands.autocomplete(player=player_autocomplete)
    async def mlbseasonstats(self, interaction: discord.Interaction, player: str):
        await interaction.response.defer(ephemeral=True)
        player_id = int(player)
        season = get_current_mlb_season()

        game_logs = await self.bot.api_client.get_mlb_player_stats_for_season(player_id, season)
        if not game_logs:
            raise StatsNotFoundException(f"Could not find stats for this player in the {season} season.")

        stats, is_pitcher = self._calculate_mlb_season_stats(game_logs)
        player_info = game_logs[0]['player']
        player_name = player_info['full_name']
        position = player_info.get('position', 'N/A')

        embed = discord.Embed(title=f"{player_name} ({position}) - {season} Season Stats", color=discord.Color.dark_green())
        if is_pitcher:
            embed.add_field(name="W-L", value=f"{stats['wins']}-{stats['losses']}", inline=True)
            embed.add_field(name="ERA", value=f"{stats['era']:.2f}", inline=True)
            embed.add_field(name="SO", value=stats['p_k'], inline=True)
            embed.add_field(name="IP", value=f"{stats['ip']:.1f}", inline=True)
            embed.add_field(name="Saves", value=stats['sv'], inline=True)
        else:
            embed.add_field(name="AVG", value=f"{stats['avg']:.3f}", inline=True)
            embed.add_field(name="HR", value=stats['hr'], inline=True)
            embed.add_field(name="RBI", value=stats['rbi'], inline=True)
            embed.add_field(name="Runs", value=stats['runs'], inline=True)
            embed.add_field(name="Hits", value=stats['hits'], inline=True)
            embed.add_field(name="SB", value=stats['sb'], inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    def _calculate_mlb_season_stats(self, game_logs: List[Dict[str, Any]]) -> (Dict[str, Any], bool):
        # Improved heuristic to determine if a player is primarily a pitcher or hitter
        games_pitched = sum(1 for g in game_logs if g.get('ip') is not None and g.get('ip') > 0)
        games_batted = sum(1 for g in game_logs if g.get('at_bats') is not None and g.get('at_bats') > 0)

        is_pitcher = games_pitched > games_batted

        if is_pitcher:
            total_ip = sum(g.get('ip', 0) or 0 for g in game_logs)
            wins = sum(1 for g in game_logs if g.get('win'))
            losses = sum(1 for g in game_logs if g.get('loss'))
            saves = sum(g.get('sv', 0) or 0 for g in game_logs)
            earned_runs = sum(g.get('er', 0) or 0 for g in game_logs)
            strikeouts = sum(g.get('p_k', 0) or 0 for g in game_logs)
            era = (earned_runs * 9) / total_ip if total_ip > 0 else 0
            return {"wins": wins, "losses": losses, "era": era, "sv": saves, "p_k": strikeouts, "ip": total_ip}, True
        else:
            at_bats = sum(g.get('at_bats', 0) or 0 for g in game_logs)
            hits = sum(g.get('hits', 0) or 0 for g in game_logs)
            hr = sum(g.get('hr', 0) or 0 for g in game_logs)
            rbi = sum(g.get('rbi', 0) or 0 for g in game_logs)
            runs = sum(g.get('runs', 0) or 0 for g in game_logs)
            sb = sum(g.get('sb', 0) or 0 for g in game_logs)
            avg = hits / at_bats if at_bats > 0 else 0
            return {"avg": avg, "hr": hr, "rbi": rbi, "runs": runs, "hits": hits, "sb": sb}, False

    @app_commands.command(name="mlbleagueleaders", description="MLB league leaders for the current season.")
    async def mlbleagueleaders(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        season = get_current_mlb_season()

        # Check cache
        if season in self._leaderboard_cache and (discord.utils.utcnow() - self._leaderboard_cache[season]['timestamp']).total_seconds() < self._LEADERBOARD_CACHE_TTL:
            await interaction.followup.send(embed=self._leaderboard_cache[season]['embed'], ephemeral=True)
            return

        all_game_logs = await self.bot.api_client.get_all_mlb_stats_for_season(season)
        if not all_game_logs:
            raise StatsNotFoundException("Could not retrieve league leader data for MLB.")

        # Process stats
        player_stats = {}
        for game in all_game_logs:
            p_id = game['player']['id']
            if p_id not in player_stats:
                player_stats[p_id] = {
                    "at_bats": 0, "hits": 0, "hr": 0, "rbi": 0, "sb": 0,
                    "wins": 0, "losses": 0, "saves": 0, "p_k": 0, "er": 0, "ip": 0,
                    "player_info": game['player'], "games_pitched": 0, "games_batted": 0
                }

            # Aggregate stats
            for stat in ["at_bats", "hits", "hr", "rbi", "sb", "wins", "losses", "saves", "p_k", "er", "ip"]:
                player_stats[p_id][stat] += game.get(stat, 0) or 0
            if (game.get('ip') or 0) > 0: player_stats[p_id]["games_pitched"] += 1
            if (game.get('at_bats') or 0) > 0: player_stats[p_id]["games_batted"] += 1

        # Calculate final stats
        for p in player_stats.values():
            p["avg"] = p["hits"] / p["at_bats"] if p["at_bats"] > 0 else 0
            p["era"] = (p["er"] * 9) / p["ip"] if p["ip"] > 0 else float('inf')

        # Get leaders
        leaders = {
            "Batting Average": sorted([p for p in player_stats.values() if p["at_bats"] > 200], key=lambda x: x["avg"], reverse=True)[:5],
            "Home Runs": sorted([p for p in player_stats.values() if p["games_batted"] > 20], key=lambda x: x["hr"], reverse=True)[:5],
            "RBIs": sorted([p for p in player_stats.values() if p["games_batted"] > 20], key=lambda x: x["rbi"], reverse=True)[:5],
            "Wins": sorted([p for p in player_stats.values() if p["games_pitched"] > 10], key=lambda x: x["wins"], reverse=True)[:5],
            "ERA": sorted([p for p in player_stats.values() if p["ip"] > 50], key=lambda x: x["era"])[:5],
            "Strikeouts": sorted([p for p in player_stats.values() if p["games_pitched"] > 10], key=lambda x: x["p_k"], reverse=True)[:5],
        }

        embed = discord.Embed(title=f"MLB League Leaders - {season} Season", color=discord.Color.dark_green())
        for stat_name, player_list in leaders.items():
            leader_text = []
            for i, p_stat in enumerate(player_list):
                name = p_stat['player_info']['full_name']
                key = {"Batting Average": "avg", "Home Runs": "hr", "RBIs": "rbi", "Wins": "wins", "ERA": "era", "Strikeouts": "p_k"}[stat_name]
                value = p_stat.get(key, 0)
                val_str = f"{value:.3f}" if key == "avg" else (f"{value:.2f}" if key == "era" else f"{value}")
                leader_text.append(f"**{i+1}.** {name} - `{val_str}`")
            embed.add_field(name=f"🏆 {stat_name}", value="\n".join(leader_text) or "N/A", inline=True)

        self._leaderboard_cache[season] = {"embed": embed, "timestamp": discord.utils.utcnow()}
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        original = getattr(error, 'original', error)
        if isinstance(original, (ApiError, StatsNotFoundException)):
            message = str(original) or "Sorry, I couldn't retrieve the MLB stats right now."
            await interaction.followup.send(message, ephemeral=True)
        else:
            print(f"An unexpected error occurred in MLBCog: {original}")
            await interaction.followup.send("An unexpected error occurred.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(MLBCog(bot))
