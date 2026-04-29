import discord
from discord.ext import commands
import asyncio
import yt_dlp
import random
import os
# ─────────────────────────────────────────────
#  CONFIGURATION  ← Fill this in
# ─────────────────────────────────────────────
DISCORD_TOKEN = os.environ.get("MTQ5ODYzMjUyODE5MjQ3MTEwMg.GiG8dM.z_ROTGiKbImRc8aoSwImuKDqnftffRaqZ6_USQ")
PREFIX = "!"
# ─────────────────────────────────────────────

# yt-dlp options for audio streaming
YDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

# ─────────────────────────────────────────────
#  BOT SETUP
# ─────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Guild state storage: guild_id → MusicPlayer
players = {}


# ─────────────────────────────────────────────
#  MUSIC PLAYER CLASS
# ─────────────────────────────────────────────
class MusicPlayer:
    def __init__(self, ctx):
        self.ctx          = ctx
        self.queue        = []          # list of dicts: {title, url, genre}
        self.current      = None        # currently playing song dict
        self.volume       = 0.5
        self.autoplay     = True
        self.is_playing   = False
        self.loop         = False

    # ── Fetch audio URL & metadata via yt-dlp ──
    async def fetch_song(self, query: str) -> dict | None:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            try:
                info = await loop.run_in_executor(
                    None, lambda: ydl.extract_info(query, download=False)
                )
                if "entries" in info:
                    info = info["entries"][0]
                return {
                    "title": info.get("title", "Unknown"),
                    "url":   info.get("url"),
                    "webpage_url": info.get("webpage_url", ""),
                    "genre": info.get("genre") or self._guess_genre(info.get("title", "")),
                    "duration": info.get("duration", 0),
                    "thumbnail": info.get("thumbnail", ""),
                }
            except Exception as e:
                print(f"[fetch_song] Error: {e}")
                return None

    # ── Rough genre guess from title keywords ──
    def _guess_genre(self, title: str) -> str:
        title_lower = title.lower()
        genre_keywords = {
            "pop":       ["pop", "taylor", "ariana", "dua lipa", "ed sheeran"],
            "hip-hop":   ["rap", "hip hop", "drake", "kendrick", "travis", "lil"],
            "rock":      ["rock", "metal", "guitar", "linkin park", "nirvana"],
            "r&b":       ["r&b", "rnb", "soul", "weeknd", "beyonce", "usher"],
            "electronic":["edm", "house", "techno", "electronic", "dj", "remix"],
            "lo-fi":     ["lo-fi", "lofi", "chill", "study", "relaxing"],
            "jazz":      ["jazz", "blues", "swing", "saxophone"],
            "classical": ["classical", "orchestra", "piano", "beethoven", "mozart"],
        }
        for genre, keywords in genre_keywords.items():
            if any(kw in title_lower for kw in keywords):
                return genre
        return "pop"   # default fallback

    # ── YouTube-based AutoPlay — search by genre ──
    async def get_autoplay_song(self, genre: str) -> str | None:
        # A pool of search queries per genre for variety
        genre_searches = {
            "pop":        ["top pop hits", "best pop songs", "popular pop music", "pop hits playlist"],
            "hip-hop":    ["top hip hop songs", "best rap music", "hip hop hits", "rap playlist"],
            "rock":       ["top rock songs", "best rock hits", "classic rock playlist", "rock music"],
            "r&b":        ["top r&b songs", "best rnb music", "r&b hits", "soul music playlist"],
            "electronic": ["top edm songs", "best electronic music", "edm hits", "house music playlist"],
            "lo-fi":      ["lofi hip hop", "chill lofi beats", "lofi study music", "relaxing lofi"],
            "jazz":       ["top jazz songs", "best jazz music", "smooth jazz playlist", "jazz hits"],
            "classical":  ["best classical music", "classical piano hits", "orchestra music", "classical playlist"],
        }
        queries = genre_searches.get(genre, [f"top {genre} songs", f"best {genre} music"])
        query = random.choice(queries)

        loop = asyncio.get_event_loop()
        ydl_opts = {**YDL_OPTIONS, "noplaylist": True, "playlistend": 10}
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await loop.run_in_executor(
                    None, lambda: ydl.extract_info(f"ytsearch10:{query}", download=False)
                )
                entries = info.get("entries", [])
                if entries:
                    pick = random.choice(entries)
                    return pick.get("webpage_url") or pick.get("url")
        except Exception as e:
            print(f"[autoplay] YouTube search error: {e}")
        return None

    # ── Core play loop ──
    async def play_next(self):
        if self.loop and self.current:
            # re-queue the same song
            self.queue.insert(0, self.current)

        if not self.queue:
            if self.autoplay and self.current:
                genre = self.current.get("genre", "pop")
                await self.ctx.send(
                    f"🔄 **AutoPlay** — finding a **{genre}** song for you..."
                )
                query = await self.get_autoplay_song(genre)
                if query:
                    song = await self.fetch_song(query)
                    if song:
                        song["genre"] = genre   # keep genre consistent
                        self.queue.append(song)
                else:
                    await self.ctx.send("❌ Could not find an autoplay song. Queue is empty.")
                    self.is_playing = False
                    return
            else:
                await self.ctx.send("✅ Queue finished! Use `!play` to add more songs.")
                self.is_playing = False
                return

        self.current   = self.queue.pop(0)
        self.is_playing = True
        vc = self.ctx.voice_client

        source = discord.FFmpegPCMAudio(self.current["url"], **FFMPEG_OPTIONS)
        source = discord.PCMVolumeTransformer(source, volume=self.volume)

        def after_play(error):
            if error:
                print(f"[after_play] {error}")
            asyncio.run_coroutine_threadsafe(self.play_next(), bot.loop)

        vc.play(source, after=after_play)

        embed = discord.Embed(
            title="🎵 Now Playing",
            description=f"**{self.current['title']}**",
            color=discord.Color.blurple()
        )
        embed.add_field(name="Genre",    value=self.current.get("genre", "Unknown"), inline=True)
        embed.add_field(name="AutoPlay", value="✅ On" if self.autoplay else "❌ Off", inline=True)
        embed.add_field(name="Loop",     value="🔁 On" if self.loop     else "➡️ Off", inline=True)
        if self.current.get("thumbnail"):
            embed.set_thumbnail(url=self.current["thumbnail"])
        embed.set_footer(text=f"Volume: {int(self.volume * 100)}%")
        await self.ctx.send(embed=embed)


# ─────────────────────────────────────────────
#  HELPER
# ─────────────────────────────────────────────
def get_player(ctx) -> MusicPlayer:
    if ctx.guild.id not in players:
        players[ctx.guild.id] = MusicPlayer(ctx)
    return players[ctx.guild.id]


async def ensure_voice(ctx) -> bool:
    """Make sure the bot is in the user's voice channel."""
    if not ctx.author.voice:
        await ctx.send("❌ You need to be in a voice channel first!")
        return False
    vc = ctx.voice_client
    if vc is None:
        await ctx.author.voice.channel.connect()
    elif vc.channel != ctx.author.voice.channel:
        await vc.move_to(ctx.author.voice.channel)
    return True


# ─────────────────────────────────────────────
#  COMMANDS
# ─────────────────────────────────────────────

@bot.command(name="play", aliases=["p"])
async def play(ctx, *, query: str):
    """Play a song or add it to the queue.  !play <song name / URL>"""
    if not await ensure_voice(ctx):
        return
    player = get_player(ctx)

    await ctx.send(f"🔍 Searching for **{query}**...")
    song = await player.fetch_song(query)
    if not song:
        await ctx.send("❌ Couldn't find that song. Try a different search.")
        return

    if player.is_playing or ctx.voice_client.is_playing():
        player.queue.append(song)
        await ctx.send(
            f"✅ Added to queue: **{song['title']}** "
            f"(Genre: `{song.get('genre','?')}`) — Position #{len(player.queue)}"
        )
    else:
        player.queue.append(song)
        await player.play_next()


@bot.command(name="skip", aliases=["s"])
async def skip(ctx):
    """Skip the current song."""
    vc = ctx.voice_client
    if vc and vc.is_playing():
        vc.stop()   # triggers after_play → play_next
        await ctx.send("⏭️ Skipped!")
    else:
        await ctx.send("❌ Nothing is playing right now.")


@bot.command(name="stop")
async def stop(ctx):
    """Stop playback and clear the queue."""
    player = get_player(ctx)
    player.queue.clear()
    player.current    = None
    player.is_playing = False
    vc = ctx.voice_client
    if vc and vc.is_playing():
        vc.stop()
    await ctx.send("⏹️ Stopped and queue cleared.")


@bot.command(name="pause")
async def pause(ctx):
    """Pause the current song."""
    vc = ctx.voice_client
    if vc and vc.is_playing():
        vc.pause()
        await ctx.send("⏸️ Paused.")
    else:
        await ctx.send("❌ Nothing is playing.")


@bot.command(name="resume", aliases=["r"])
async def resume(ctx):
    """Resume a paused song."""
    vc = ctx.voice_client
    if vc and vc.is_paused():
        vc.resume()
        await ctx.send("▶️ Resumed!")
    else:
        await ctx.send("❌ Nothing is paused.")


@bot.command(name="volume", aliases=["vol", "v"])
async def volume(ctx, vol: int):
    """Set volume 1–100.  !volume 75"""
    if not 1 <= vol <= 100:
        await ctx.send("❌ Volume must be between 1 and 100.")
        return
    player = get_player(ctx)
    player.volume = vol / 100
    vc = ctx.voice_client
    if vc and vc.source:
        vc.source.volume = player.volume
    await ctx.send(f"🔊 Volume set to **{vol}%**")


@bot.command(name="queue", aliases=["q"])
async def queue(ctx):
    """Show the current queue."""
    player = get_player(ctx)
    if not player.queue and not player.current:
        await ctx.send("📭 The queue is empty.")
        return

    embed = discord.Embed(title="🎶 Music Queue", color=discord.Color.blurple())
    if player.current:
        embed.add_field(
            name="▶️ Now Playing",
            value=f"**{player.current['title']}** — `{player.current.get('genre','?')}`",
            inline=False
        )
    if player.queue:
        lines = [
            f"`{i+1}.` {s['title']} — `{s.get('genre','?')}`"
            for i, s in enumerate(player.queue[:10])
        ]
        embed.add_field(name="📋 Up Next", value="\n".join(lines), inline=False)
        if len(player.queue) > 10:
            embed.set_footer(text=f"...and {len(player.queue)-10} more songs")
    await ctx.send(embed=embed)


@bot.command(name="autoplay", aliases=["ap"])
async def autoplay(ctx):
    """Toggle AutoPlay (genre-based) on or off."""
    player = get_player(ctx)
    player.autoplay = not player.autoplay
    state = "✅ **ON**" if player.autoplay else "❌ **OFF**"
    await ctx.send(f"🔄 AutoPlay is now {state}")


@bot.command(name="loop", aliases=["l"])
async def loop_cmd(ctx):
    """Toggle loop mode for the current song."""
    player = get_player(ctx)
    player.loop = not player.loop
    state = "🔁 **ON**" if player.loop else "➡️ **OFF**"
    await ctx.send(f"Loop is now {state}")


@bot.command(name="nowplaying", aliases=["np"])
async def nowplaying(ctx):
    """Show what's currently playing."""
    player = get_player(ctx)
    if not player.current:
        await ctx.send("❌ Nothing is playing right now.")
        return
    embed = discord.Embed(
        title="🎵 Now Playing",
        description=f"**{player.current['title']}**",
        color=discord.Color.green()
    )
    embed.add_field(name="Genre",    value=player.current.get("genre", "Unknown"), inline=True)
    embed.add_field(name="AutoPlay", value="✅" if player.autoplay else "❌", inline=True)
    embed.add_field(name="Loop",     value="🔁" if player.loop     else "➡️", inline=True)
    embed.set_footer(text=f"Volume: {int(player.volume*100)}%")
    if player.current.get("thumbnail"):
        embed.set_thumbnail(url=player.current["thumbnail"])
    await ctx.send(embed=embed)


@bot.command(name="leave", aliases=["disconnect", "dc"])
async def leave(ctx):
    """Disconnect the bot from the voice channel."""
    vc = ctx.voice_client
    if vc:
        player = get_player(ctx)
        player.queue.clear()
        player.is_playing = False
        await vc.disconnect()
        players.pop(ctx.guild.id, None)
        await ctx.send("👋 Disconnected!")
    else:
        await ctx.send("❌ I'm not in a voice channel.")


@bot.command(name="commands", aliases=["help2"])
async def commands_list(ctx):
    """Show all available commands."""
    embed = discord.Embed(
        title="🎵 Music Bot Commands",
        color=discord.Color.blurple()
    )
    cmds = [
        ("!play <song>",    "Play a song or add to queue"),
        ("!skip",           "Skip the current song"),
        ("!stop",           "Stop and clear the queue"),
        ("!pause",          "Pause playback"),
        ("!resume",         "Resume playback"),
        ("!volume <1-100>", "Set volume"),
        ("!queue",          "Show the queue"),
        ("!nowplaying",     "Show current song"),
        ("!autoplay",       "Toggle genre-based AutoPlay"),
        ("!loop",           "Toggle loop current song"),
        ("!leave",          "Disconnect the bot"),
    ]
    for name, value in cmds:
        embed.add_field(name=name, value=value, inline=False)
    await ctx.send(embed=embed)


# ─────────────────────────────────────────────
#  EVENTS
# ─────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening,
        name="!commands for help"
    ))

@bot.event
async def on_voice_state_update(member, before, after):
    """Auto-disconnect if bot is alone in voice channel."""
    if member == bot.user:
        return
    vc = member.guild.voice_client
    if vc and len(vc.channel.members) == 1:
        await asyncio.sleep(30)
        if vc.is_connected() and len(vc.channel.members) == 1:
            await vc.disconnect()
            players.pop(member.guild.id, None)

# ─────────────────────────────────────────────
#  RUN
# ─────────────────────────────────────────────
bot.run(DISCORD_TOKEN)
