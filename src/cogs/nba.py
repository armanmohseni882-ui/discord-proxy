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

LEADER_STAT_CHOICES = ["pts", "reb", "ast", "stl", "blk"]

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
        player_id, num_games = int(player), int(games)

        season = get_current_nba_season()
        game_logs = await self.bot.api_client.get_nba_player_stats_for_season(player_id, season)

        if len(game_logs) < num_games:
            prev_season_logs = await self.bot.api_client.get_nba_player_stats_for_season(player_id, season - 1)
            game_logs.extend(prev_season_logs)

        played_games = sorted([g for g in game_logs if g.get('min')], key=lambda x: x['game']['date'], reverse=True)
        recent_games = played_games[:num_games]

        if not recent_games:
            raise StatsNotFoundException("Could not find recent game stats for this player.")

        avg_stat, stat_name, player_name = self._calculate_average_stat(recent_games, stat)

        embed = discord.Embed(title=f"{player_name} - {stat_name}", description=f"Average over the last {len(recent_games)} games played.", color=discord.Color.blue())
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

        averages_data = await self.bot.api_client.get_nba_season_averages(player_id, season)
        if not averages_data or not averages_data.get("data"):
            raise StatsNotFoundException(f"Could not find season stats for this player in the {season} season.")

        data = averages_data["data"][0]
        stats = data["stats"]
        player_name = f"{data['player']['first_name']} {data['player']['last_name']}"

        embed = discord.Embed(title=f"{player_name} - {season} Season Averages", color=discord.Color.gold())
        embed.add_field(name="PPG", value=f"{stats.get('pts', 0):.1f}", inline=True)
        embed.add_field(name="RPG", value=f"{stats.get('reb', 0):.1f}", inline=True)
        embed.add_field(name="APG", value=f"{stats.get('ast', 0):.1f}", inline=True)
        embed.add_field(name="SPG", value=f"{stats.get('stl', 0):.1f}", inline=True)
        embed.add_field(name="BPG", value=f"{stats.get('blk', 0):.1f}", inline=True)
        embed.add_field(name="FG%", value=f"{stats.get('fg_pct', 0)*100:.1f}%", inline=True)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="nbaleagueleaders", description="NBA league leaders for the current season.")
    async def nbaleagueleaders(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        season = get_current_nba_season()

        embed = discord.Embed(title=f"NBA League Leaders - {season} Season", color=discord.Color.purple())

        tasks = [self.bot.api_client.get_nba_leaders(season, stat) for stat in LEADER_STAT_CHOICES]
        results = await asyncio.gather(*tasks)

        for leaders_data in results:
            if not leaders_data or not leaders_data.get("data"): continue

            stat_name = leaders_data["data"][0]["stat_type"].upper()
            leader_text = []
            for i, p_stat in enumerate(leaders_data["data"][:5]):
                name = f"{p_stat['player']['first_name']} {p_stat['player']['last_name']}"
                value = p_stat.get("value", 0)
                leader_text.append(f"**{i+1}.** {name} - `{value:.1f}`")

            embed.add_field(name=f"🏆 {stat_name}", value="\n".join(leader_text), inline=True)

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
