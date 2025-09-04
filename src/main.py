import os
import discord
from discord.ext import commands
from dotenv import load_dotenv
from src.utils.api_client import ApiClient

class SportsBot(commands.Bot):
    def __init__(self, api_key: str):
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.api_client = ApiClient(api_key)

    async def setup_hook(self):
        print("Running setup hook...")
        await self.api_client.connect()

        # Define cogs to load
        cogs_to_load = ['nba', 'nfl', 'mlb']
        for cog in cogs_to_load:
            try:
                await self.load_extension(f'src.cogs.{cog}')
                print(f"Loaded cog: {cog}")
            except Exception as e:
                print(f"Failed to load cog {cog}: {e}")

        await self.tree.sync()
        print("Setup hook complete.")

    async def close(self):
        await super().close()
        await self.api_client.close()
        print("Bot has shut down.")

def main():
    load_dotenv()

    DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
    API_KEY = os.getenv("BALLDONTLIE_API_KEY")

    if not DISCORD_TOKEN or DISCORD_TOKEN == "YOUR_DISCORD_BOT_TOKEN":
        print("Error: DISCORD_TOKEN not found or not set. Please create a .env file and set the token.")
        return
    if not API_KEY:
        print("Error: BALLDONTLIE_API_KEY not found. Please add it to your .env file.")
        return

    bot = SportsBot(api_key=API_KEY)

    @bot.event
    async def on_ready():
        print(f'Logged in as {bot.user.name} ({bot.user.id})')
        print('-------------------------------------------')

    bot.run(DISCORD_TOKEN)

if __name__ == '__main__':
    main()
