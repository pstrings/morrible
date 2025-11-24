# GEMINI.md

## Project Overview

This is a Python-based Discord bot named "Morrible". It is built using the `discord.py` library and utilizes `SQLAlchemy` with an `aiosqlite` backend for database management. The bot's primary function is to provide moderation and server management tools.

The project is structured using `cogs`, which are modules that encapsulate different features of the bot. Key features include:

*   **Moderation:** A comprehensive suite of moderation commands such as `warn`, `kick`, `ban`, `unban`, `mute`, `unmute`, `timeout`, `untimeout`, `purge`, and `slowmode`. All moderation actions are logged in a database and can be sent to a designated log channel.
*   **Infraction Tracking:** The bot records every moderation action, allowing moderators to view a user's history and clear it if necessary.
*   **Partnership System:** A ticket-based system for managing server partnerships.
*   **Reaction Roles:** Functionality for users to self-assign roles by reacting to a message.
*   **Automod (Disabled):** The codebase includes a disabled auto-moderation system designed to automatically punish users based on configurable thresholds.

The bot uses a role-based hierarchy for command permissions, ensuring that only authorized staff can perform sensitive actions.

## Building and Running

### 1. Installation

The project's dependencies are listed in `requirements.txt`. Install them using pip:

```bash
pip install -r requirements.txt
```

### 2. Configuration

The bot requires a Discord bot token to run. This is managed through a `.env` file in the root directory.

1.  Create a file named `.env`.
2.  Add your bot token to the file like this:

    ```
    DISCORD_TOKEN=your_bot_token_here
    ```

### 3. Running the Bot

The main entry point for the bot is `main.py`. To run the bot, execute the following command from the root directory:

```bash
python main.py
```

Upon first run, the bot will create a `morrible.db` SQLite database file.

## Development Conventions

*   **Architecture:** The bot follows a cog-based architecture, with each major feature area (e.g., moderation, partnership) residing in its own file within the `cogs/` directory. This is the standard practice for `discord.py` bots.
*   **Database:** Database interactions are handled asynchronously using `SQLAlchemy` and `async_sessionmaker`. The database models and initialization logic are located in `database/database.py`.
*   **Asynchronous Code:** The entire codebase is asynchronous, using Python's `async`/`await` syntax.
*   **Slash Commands:** The bot uses Discord's slash commands (`@app_commands`) for user interaction, which are synced globally on startup.
*   **Logging:** The bot uses Python's built-in `logging` module to log events and actions.
