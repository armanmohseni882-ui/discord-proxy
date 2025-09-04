import discord
from discord import app_commands
from discord.ext import commands
import asyncio
from typing import List, Dict, Any

from src.utils.api_client import get_current_nfl_season
from src.utils.exceptions import ApiError, StatsNotFoundException

NFL_STAT_CHOICES = [
    app_commands.Choice(name="Passing Yards", value="passing_yards"),
    app_commands.Choice(name="Passing TDs", value="passing_touchdowns"),
    app_commands.Choice(name="Rushing Yards", value="rushing_yards"),
    app_commands.Choice(name="Rushing TDs", value="rushing_touchdowns"),
    app_commands.Choice(name="Receptions", value="receptions"),
    app_commands.Choice(name="Receiving Yards", value="receiving_yards"),
    app_commands.Choice(name="Receiving TDs", value="receiving_touchdowns"),
]

class NFLCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def player_autocomplete(self, interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        if not current: return []
        try:
            players = await self.bot.api_client.get_nfl_players(search=current)
            if not players or not players.get("data"): return []

            choices = []
            for player in players["data"]:
                team = player.get('team', {}).get('abbreviation', 'N/A')
                pos = player.get('position_abbreviation', 'N/A')
                name = f"{player['first_name']} {player['last_name']} ({team}) - {pos}"
                choices.append(app_commands.Choice(name=name, value=str(player['id'])))
                if len(choices) == 25: break
            return choices
        except ApiError:
            return []

    @app_commands.command(name="nflstats", description="Get a player's average stats over their last N weeks played.")
    @app_commands.autocomplete(player=player_autocomplete)
    @app_commands.choices(stat=NFL_STAT_CHOICES)
    @app_commands.choices(games=[app_commands.Choice(name="Last 5 Weeks", value="5"), app_commands.Choice(name="Last 10 Weeks", value="10")])
    async def nflstats(self, interaction: discord.Interaction, player: str, stat: str, games: str):
        await interaction.response.defer(ephemeral=True)
        player_id, num_weeks = int(player), int(games)

        season = get_current_nfl_season()
        # NFL API returns weekly stats, not game-by-game
        weekly_logs_data = await self.bot.api_client.get_nfl_player_stats_for_season(player_id, season)

        if not weekly_logs_data or not weekly_logs_data.get("data"):
             raise StatsNotFoundException("Could not find recent weekly stats for this player.")

        # Sort by week and get the most recent weeks
        sorted_weeks = sorted(weekly_logs_data["data"], key=lambda x: x['game']['week'], reverse=True)
        recent_weeks = sorted_weeks[:num_weeks]

        if not recent_weeks:
            raise StatsNotFoundException("Could not find recent weekly stats for this player.")

        total = sum(g.get(stat, 0) or 0 for g in recent_weeks)
        avg = total / len(recent_weeks)

        stat_name = next((c.name for c in NFL_STAT_CHOICES if c.value == stat), stat)
        player_name = f"{recent_weeks[0]['player']['first_name']} {recent_weeks[0]['player']['last_name']}"

        embed = discord.Embed(title=f"{player_name} - {stat_name}", description=f"Average over the last {len(recent_weeks)} weeks played.", color=discord.Color.dark_red())
        embed.add_field(name="Average", value=f"**{avg:.1f}**")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="nflseasonstats", description="Get a player's position-specific stats for the current season.")
    @app_commands.autocomplete(player=player_autocomplete)
    async def nflseasonstats(self, interaction: discord.Interaction, player: str):
        await interaction.response.defer(ephemeral=True)
        player_id = int(player)
        season = get_current_nfl_season()

        stats_data = await self.bot.api_client.get_nfl_season_stats(player_id, season)

        if not stats_data or not stats_data.get("data"):
            raise StatsNotFoundException(f"Could not find season stats for this player in the {season} season.")

        stats = stats_data["data"][0]
        p_info = stats["player"]
        player_name = f"{p_info['first_name']} {p_info['last_name']}"
        position = p_info.get('position_abbreviation', 'N/A')

        embed = discord.Embed(title=f"{player_name} ({position}) - {season} Season Stats", color=discord.Color.dark_gold())
        self._add_nfl_season_stats_fields(embed, position, stats)
        await interaction.followup.send(embed=embed, ephemeral=True)

    def _add_nfl_season_stats_fields(self, embed: discord.Embed, position: str, stats: dict):
        # Use full position name for more robust matching
        if position == 'Quarterback':
            fields = [("Pass Yds", "passing_yards"), ("Pass TDs", "passing_touchdowns"), ("INTs", "passing_interceptions"), ("Comp %", "passing_completion_pct"), ("Rush Yds", "rushing_yards"), ("Rush TDs", "rushing_touchdowns")]
        elif position in ['Running Back', 'Fullback']:
            fields = [("Rush Yds", "rushing_yards"), ("Rush Att", "rushing_attempts"), ("Rush TDs", "rushing_touchdowns"), ("Rec Yds", "receiving_yards"), ("Receptions", "receptions"), ("Rec TDs", "receiving_touchdowns")]
        elif position in ['Wide Receiver', 'Tight End']:
            fields = [("Rec Yds", "receiving_yards"), ("Receptions", "receptions"), ("Targets", "receiving_targets"), ("Rec TDs", "receiving_touchdowns"), ("Rush Yds", "rushing_yards"), ("Rush TDs", "rushing_touchdowns")]
        else:
            embed.description = "No specific stat layout for this position."
            return

        for name, key in fields:
            value = stats.get(key)
            if value is not None:
                embed.add_field(name=name, value=f"{value:.1f}" if isinstance(value, float) else value, inline=True)

    @app_commands.command(name="nflleagueleaders", description="NFL league leaders for the current season.")
    async def nflleagueleaders(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        season = get_current_nfl_season()

        embed = discord.Embed(title=f"NFL League Leaders - {season} Season", color=discord.Color.dark_blue())

        leader_stats = {
            "Passing Yards": "passing_yards", "Passing TDs": "passing_touchdowns", "Rushing Yards": "rushing_yards",
            "Rushing TDs": "rushing_touchdowns", "Receptions": "receptions", "Receiving Yards": "receiving_yards",
            "Receiving TDs": "receiving_touchdowns", "Interceptions": "passing_interceptions"
        }

        for stat_name, stat_key in leader_stats.items():
            leaders_data = await self.bot.api_client.get_nfl_league_leaders(season, stat_key)
            if not leaders_data or not leaders_data.get("data"): continue

            leader_text = []
            for i, p_stat in enumerate(leaders_data["data"][:5]):
                p_info = p_stat["player"]
                name = f"{p_info['first_name']} {p_info['last_name']}"
                value = p_stat.get(stat_key)
                leader_text.append(f"**{i+1}.** {name} - `{value}`")

            embed.add_field(name=f"🏆 {stat_name}", value="\n".join(leader_text), inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        original = getattr(error, 'original', error)
        if isinstance(original, (ApiError, StatsNotFoundException)):
            message = str(original) or "Sorry, I couldn't retrieve the NFL stats right now."
            await interaction.followup.send(message, ephemeral=True)
        else:
            print(f"An unexpected error occurred in NFLCog: {original}")
            await interaction.followup.send("An unexpected error occurred.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(NFLCog(bot))
