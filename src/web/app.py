import os
import threading
import time
import requests
from flask import Flask, render_template, request, redirect, url_for
import discord
from discord.ext import tasks
from discord.errors import Forbidden

# =====================
# READ SECRETS FROM ENVIRONMENT
# =====================
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN")
GUILD_ID = int(os.environ.get("GUILD_ID"))
CHANNEL_ID = int(os.environ.get("CHANNEL_ID"))
ROLE_ID = int(os.environ.get("ROLE_ID"))

if not all([DISCORD_TOKEN, GUILD_ID, CHANNEL_ID, ROLE_ID]):
    raise RuntimeError("One or more required environment variables are missing!")

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
intents = discord.Intents.default()
client = discord.Client(intents=intents)

async def send_ping(message):
    try:
        guild = await client.fetch_guild(GUILD_ID)
        channel = await guild.fetch_channel(CHANNEL_ID)
        await channel.send(f"<@&{ROLE_ID}> {message}")
        log("Discord message sent")

    except Forbidden:
        log("ERROR: Discord Forbidden (missing permissions)")
    except Exception as e:
        log(f"ERROR sending Discord message: {e}")

@tasks.loop(seconds=7)  # fast polling
async def monitor_vatsim():
    await client.wait_until_ready()
    log("monitor_vatsim tick")

    try:
        response = requests.get(
            "https://data.vatsim.net/v3/vatsim-data.json",
            timeout=10
        )
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
    threading.Thread(target=run_discord, daemon=True).start()
    app.run(debug=True, use_reloader=False)
