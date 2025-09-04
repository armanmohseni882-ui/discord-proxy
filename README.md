# Sports Stats Discord Bot

A Discord bot that provides statistics for NBA, NFL, and MLB using the balldontlie API. The bot uses slash commands and is designed to be deployed easily on Replit.

## Features

- **Multi-Sport Coverage**: Get stats for NBA, NFL, and MLB.
- **Player Stats**: Get player stats for recent games (`/nbastats`, `/nflstats`, `/mlbstats`).
- **Season Stats**: Get full season stats for a player, with position-specific data for NFL and MLB (`/nbaseasonstats`, `/nflseasonstats`, `/mlbseasonstats`).
- **League Leaders**: See the top 5 league leaders for key stats in the NFL (`/nflleagueleaders`). (Note: NBA and MLB leader commands require a higher API tier).
- **Autocomplete**: Easy-to-use player search with autocomplete on all commands.
- **Clean UI**: All responses are sent as clean, formatted Discord embeds.

## How to Deploy (Easy Method - Replit)

The easiest way to run this bot 24/7 for free is by using [Replit](https://replit.com).

### Step 1: Create a Replit Account
1. Go to `replit.com` and sign up, preferably by connecting your GitHub account.
2. If you don't use GitHub to sign up, link it later in your account settings.

### Step 2: Import the Repository
1. On your Replit dashboard, click **+ Create Repl**.
2. In the top right of the popup, click **Import from GitHub**.
3. Select this repository to import it. If it was private, you may need to make it public first in the repository's GitHub settings.
4. Replit will automatically install all the needed packages.

### Step 3: Add Your Bot Token
1. In the Replit project, look for the **Secrets** tool in the left-hand sidebar (it has a 🔒 padlock icon).
2. Create a new secret:
   - For the **key**, type `DISCORD_TOKEN`.
   - For the **value**, paste your actual Discord Bot Token. (You can get this from the [Discord Developer Portal](https://discord.com/developers/applications) under your bot's settings).
3. Click **Add new secret**.

### Step 4: Run the Bot
1. Simply click the big green **Run** button at the top of the screen.
2. Replit will start the bot. You should see a "Logged in as..." message in the console. Your bot is now online!
3. To keep it running 24/7, you may need to configure Replit's deployment features, but for basic use, the Run button is all you need.

---
*This bot was developed by Jules, your AI Software Engineer.*
