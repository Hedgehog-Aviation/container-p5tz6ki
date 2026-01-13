import os
import threading
import time
import requests
from flask import Flask, render_template, request, redirect, url_for
import discord
from discord.ext import tasks
from discord.errors import Forbidden

# =====================
# READ SECRETS FROM ENVIRONMENT (GitHub-ready)
# =====================
def get_env_int(name: str) -> int:
    val = os.environ.get(name)
    if val is None:
        raise RuntimeError(f"Environment variable {name} is missing! Make sure it's in GitHub Secrets.")
    try:
        return int(val)
    except ValueError:
        raise RuntimeError(f"Environment variable {name} must be an integer, got: {val}")

# Discord integration is optional - if token is missing, Discord features will be disabled
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
DISCORD_ENABLED = bool(DISCORD_TOKEN)

# These are only required when Discord is enabled
GUILD_ID = None
CHANNEL_ID = None
ROLE_ID = None

if DISCORD_ENABLED:
    try:
        GUILD_ID = get_env_int("GUILD_ID")
        CHANNEL_ID = get_env_int("CHANNEL_ID")
        ROLE_ID = get_env_int("ROLE_ID")
    except RuntimeError as e:
        # Use print here since log() function is not yet defined
        print(f"WARNING: Discord token provided but configuration incomplete: {e}")
        print("Discord integration will be disabled.")
        DISCORD_ENABLED = False

# =====================
# APP STATE
# =====================
monitored_stations = set()
station_status = {}
logs = []
debug_mode = False

# =====================
# FLASK APP
# =====================
app = Flask(__name__)

def log(msg):
    timestamp = time.strftime("%H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    print(entry)
    logs.append(entry)
    if len(logs) > 300:
        logs.pop(0)

@app.route("/", methods=["GET", "POST"])
def index():
    global debug_mode

    if request.method == "POST":
        if "add_station" in request.form:
            station = request.form["station"].upper().strip()
            if station:
                monitored_stations.add(station)
                log(f"Started monitoring {station}")

        elif "remove_station" in request.form:
            station = request.form["remove_station"]
            monitored_stations.discard(station)
            station_status.pop(station, None)
            log(f"Stopped monitoring {station}")

        elif "toggle_debug" in request.form:
            debug_mode = not debug_mode
            log(f"Debug mode {'ENABLED' if debug_mode else 'DISABLED'}")

        return redirect(url_for("index"))

    return render_template(
        "index.html",
        stations=sorted(monitored_stations),
        logs=logs,
        debug_mode=debug_mode
    )

# =====================
# DISCORD BOT
# =====================
# Only initialize Discord client if Discord is enabled
client = None

async def send_ping(message: str):
    if not DISCORD_ENABLED or client is None:
        log("Discord integration disabled - message not sent")
        return
    
    try:
        guild = await client.fetch_guild(GUILD_ID)
        channel = await guild.fetch_channel(CHANNEL_ID)
        await channel.send(f"<@&{ROLE_ID}> {message}")
        log("Discord message sent")
    except Forbidden:
        log("ERROR: Discord Forbidden (missing permissions)")
    except Exception as e:
        log(f"ERROR sending Discord message: {e}")

if DISCORD_ENABLED:
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    
    @tasks.loop(seconds=5)  # 5-second polling for near real-time updates
    async def monitor_vatsim():
        await client.wait_until_ready()
        log("monitor_vatsim tick")

        try:
            response = requests.get("https://data.vatsim.net/v3/vatsim-data.json", timeout=10)
            data = response.json()

            controllers = data.get("controllers", [])
            if not isinstance(controllers, list):
                log("WARNING: VATSIM 'controllers' key is missing or invalid")
                controllers = []

            online_callsigns = {ctrl.get("callsign") for ctrl in controllers if "callsign" in ctrl}

            for station in monitored_stations:
                is_online = station in online_callsigns
                was_online = station_status.get(station, False)

                if is_online and not was_online:
                    await send_ping(f"🟢 **{station}** is now ONLINE")
                    log(f"{station} logged ON")
                elif not is_online and was_online:
                    await send_ping(f"🔴 **{station}** is now OFFLINE")
                    log(f"{station} logged OFF")

                station_status[station] = is_online

        except Exception as e:
            log(f"ERROR in VATSIM section: {e}")

        # Debug mode always fires every 5 seconds
        if debug_mode:
            await send_ping("🧪 Debug mode test ping")
            log("Debug ping sent")

    @client.event
    async def on_ready():
        log(f"Discord bot connected as {client.user}")
        if not monitor_vatsim.is_running():
            monitor_vatsim.start()
            log("monitor_vatsim task started")

    def run_discord():
        client.run(DISCORD_TOKEN)

# =====================
# MAIN
# =====================
if __name__ == "__main__":
    # Log startup configuration
    if DISCORD_ENABLED:
        log("🟢 Discord integration ENABLED - notifications will be sent")
    else:
        log("🔴 Discord integration DISABLED - DISCORD_TOKEN not configured")
    
    # Only start Discord bot if enabled
    if DISCORD_ENABLED:
        threading.Thread(target=run_discord, daemon=True).start()
    
    port = int(os.environ.get("PORT", 8080))  # cloud hosting will set PORT
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
