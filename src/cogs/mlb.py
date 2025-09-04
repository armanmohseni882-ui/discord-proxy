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

LEADER_HITTING_STATS = {"Home Runs": "batting_hr", "RBIs": "batting_rbi", "Batting Average": "batting_avg", "Hits": "batting_h", "Stolen Bases": "batting_sb"}
LEADER_PITCHING_STATS = {"Wins": "pitching_w", "ERA": "pitching_era", "Saves": "pitching_sv", "Strikeouts": "pitching_k"}

class MLBCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

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
        player_id, season = int(player), get_current_mlb_season()

        stats_data = await self.bot.api_client.get_mlb_season_stats(player_id, season)
        if not stats_data or not stats_data.get("data"):
            raise StatsNotFoundException(f"Could not find season stats for this player in the {season} season.")

        stats = stats_data["data"][0]
        player_info = stats["player"]
        player_name = player_info['full_name']
        position = player_info.get('position', 'N/A')

        embed = discord.Embed(title=f"{player_name} ({position}) - {season} Season Stats", color=discord.Color.dark_green())

        is_pitcher = (stats.get('pitching_gp') or 0) > (stats.get('batting_gp') or 0)

        if is_pitcher:
            embed.add_field(name="W-L", value=f"{stats.get('pitching_w', 0)}-{stats.get('pitching_l', 0)}", inline=True)
            embed.add_field(name="ERA", value=f"{stats.get('pitching_era', 0):.2f}", inline=True)
            embed.add_field(name="SO", value=stats.get('pitching_k', 0), inline=True)
            embed.add_field(name="IP", value=f"{stats.get('pitching_ip', 0):.1f}", inline=True)
            embed.add_field(name="Saves", value=stats.get('pitching_sv', 0), inline=True)
        else:
            embed.add_field(name="AVG", value=f"{stats.get('batting_avg', 0):.3f}", inline=True)
            embed.add_field(name="HR", value=stats.get('batting_hr', 0), inline=True)
            embed.add_field(name="RBI", value=stats.get('batting_rbi', 0), inline=True)
            embed.add_field(name="Runs", value=stats.get('batting_r', 0), inline=True)
            embed.add_field(name="Hits", value=stats.get('batting_h', 0), inline=True)
            embed.add_field(name="SB", value=stats.get('batting_sb', 0), inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="mlbleagueleaders", description="MLB league leaders for the current season.")
    async def mlbleagueleaders(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        season = get_current_mlb_season()

        embed = discord.Embed(title=f"MLB League Leaders - {season} Season", color=discord.Color.dark_green())

        all_stats_to_fetch = {**LEADER_HITTING_STATS, **LEADER_PITCHING_STATS}
        tasks = [self.bot.api_client.get_mlb_league_leaders(season, stat) for stat in all_stats_to_fetch.values()]
        results = await asyncio.gather(*tasks)

        leaders_by_category = {name: [] for name in all_stats_to_fetch.keys()}

        for leaders_data in results:
            if not leaders_data or not leaders_data.get("data"): continue

            # Determine which stat this result is for
            p_stat = leaders_data["data"][0]
            stat_key = next((key for key in p_stat if key.startswith(('batting_', 'pitching_')) and key in all_stats_to_fetch.values()), None)
            if not stat_key: continue

            stat_name = next(name for name, key in all_stats_to_fetch.items() if key == stat_key)

            for p_data in leaders_data["data"][:5]:
                name = p_data['player']['full_name']
                value = p_data.get(stat_key)
                val_str = f"{value:.3f}" if stat_key == "batting_avg" else (f"{value:.2f}" if stat_key == "pitching_era" else f"{value}")
                leaders_by_category[stat_name].append(f"**{len(leaders_by_category[stat_name])+1}.** {name} - `{val_str}`")

        for stat_name, leader_text_list in leaders_by_category.items():
            embed.add_field(name=f"🏆 {stat_name}", value="\n".join(leader_text_list) or "N/A", inline=True)

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
