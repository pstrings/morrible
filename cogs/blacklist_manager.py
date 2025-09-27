import discord
from discord import app_commands
from discord.ext import commands

from utils.load_blacklist import (
    save_dynamic_word,
    remove_dynamic_word,
    list_dynamic_words,
    compile_blacklist_patterns,
)


class BlacklistManager(commands.Cog):
    """
    Admin-only manager for dynamic blacklist words.
    Detection is centralized in AutoMod (regex + AI).
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._compiled_patterns = compile_blacklist_patterns()

    # -----------------------------
    # Helpers for AutoMod
    # -----------------------------
    @property
    def compiled_patterns(self):
        return self._compiled_patterns

    def refresh_patterns(self):
        self._compiled_patterns = compile_blacklist_patterns()

    # -----------------------------
    # Slash Commands
    # -----------------------------
    @app_commands.command(name="blacklist_add", description="Add a word to the dynamic blacklist")
    @app_commands.describe(word="Word to be added to blacklist")
    @app_commands.guild_install()
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def add_blacklist(self, interaction: discord.Interaction, word: str):
        word = word.strip().lower()

        if len(word) < 2:
            await interaction.response.send_message("❌ Word must be at least 2 characters", ephemeral=True)
            return

        if len(word) > 50:
            await interaction.response.send_message("❌ Word must be less than 50 characters", ephemeral=True)
            return

        words = save_dynamic_word(word)
        self.refresh_patterns()

        await interaction.response.send_message(
            f"✅ Added `{word}` to the dynamic blacklist. Total words: {len(words)}",
            ephemeral=True
        )

    @app_commands.command(name="blacklist_remove", description="Remove a word from the dynamic blacklist")
    @app_commands.describe(word="Word to be remove from blacklist")
    @app_commands.guild_install()
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_blacklist(self, interaction: discord.Interaction, word: str):
        word = word.strip().lower()
        words = remove_dynamic_word(word)
        self.refresh_patterns()

        await interaction.response.send_message(
            f"✅ Removed `{word}` from the dynamic blacklist. Total words: {len(words)}",
            ephemeral=True
        )

    @app_commands.command(name="blacklist_list", description="View dynamic blacklisted words")
    @app_commands.guild_install()
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def list_blacklist(self, interaction: discord.Interaction):
        dynamic_words = list_dynamic_words()

        if not dynamic_words:
            embed = discord.Embed(
                title="🚫 Dynamic Blacklisted Words",
                description="No dynamic words blacklisted.",
                color=discord.Color.blue()
            )
        else:
            # Split into chunks if too long
            words_text = ", ".join(f"`{word}`" for word in dynamic_words)
            if len(words_text) > 1000:
                words_text = words_text[:1000] + "..."

            embed = discord.Embed(
                title="🚫 Dynamic Blacklisted Words",
                color=discord.Color.red()
            )
            embed.add_field(
                name=f"Words ({len(dynamic_words)})", value=words_text, inline=False)

        embed.set_footer(
            text="Static pattern-based blacklist is always active (not editable).")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(BlacklistManager(bot))
