import asyncio
import aiohttp
from bs4 import BeautifulSoup
import logging
import socket

logging.basicConfig(format='[%(asctime)s - %(levelname)s] %(message)s', level=logging.INFO)
logger = logging.getLogger("ProxyManager")

class Proxy:
    def __init__(self, ip, port, proxy_type="HTTP"):
        self.ip = ip
        self.port = int(port)
        self.type = proxy_type.upper()  # HTTP, SOCKS4, SOCKS5

    def __str__(self):
        return f"{self.ip}:{self.port}"

class ProxyManager:
    def __init__(self, sources):
        self.sources = sources
        self.proxies = set()

    async def fetch_proxies(self, url):
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        if "proxyscrape" in url:
                            for line in text.splitlines():
                                if ":" in line:
                                    ip, port = line.split(":")
                                    self.proxies.add(Proxy(ip, port, "SOCKS5"))
                        else:
                            soup = BeautifulSoup(text, 'html.parser')
                            for row in soup.select('tr'):
                                cols = row.find_all('td')
                                if len(cols) > 1:
                                    ip, port = cols[0].text.strip(), cols[1].text.strip()
                                    self.proxies.add(Proxy(ip, port, "HTTP"))
            except Exception as e:
                logger.error(f"Failed to fetch proxies from {url}: {e}")

    async def check_proxy(self, proxy, test_url="http://httpbin.org/get"):
        try:
            if proxy.type == "HTTP":
                async with aiohttp.ClientSession() as session:
                    async with session.get(test_url, proxy=f"http://{proxy}", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        return resp.status == 200
            else:  # SOCKS4/5
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect((proxy.ip, proxy.port))
                sock.close()
                return True
        except:
            return False

    async def gather_proxies(self):
        tasks = [self.fetch_proxies(source) for source in self.sources]
        await asyncio.gather(*tasks)
        logger.info(f"Collected {len(self.proxies)} raw proxies.")

        # Kiểm tra proxy bất đồng bộ
        check_tasks = [self.check_proxy(proxy) for proxy in self.proxies]
        results = await asyncio.gather(*check_tasks)
        self.proxies = {p for p, r in zip(self.proxies, results) if r}
        logger.info(f"Found {len(self.proxies)} working proxies.")
        return self.proxies