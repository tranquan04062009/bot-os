import asyncio
import aiohttp
from bs4 import BeautifulSoup
from PyRoxy import Proxy, ProxyChecker, ProxyType
import logging

logging.basicConfig(format='[%(asctime)s - %(levelname)s] %(message)s', level=logging.INFO)
logger = logging.getLogger("ProxyManager")

class ProxyManager:
    def __init__(self, sources):
        self.sources = sources
        self.proxies = set()

    async def fetch_proxies(self, url, proxy_type=ProxyType.SOCKS5):
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        text = await resp.text()
                        if "proxyscrape" in url:
                            for line in text.splitlines():
                                if ":" in line:
                                    self.proxies.add(Proxy(line.strip(), proxy_type))
                        else:
                            soup = BeautifulSoup(text, 'html.parser')
                            for row in soup.select('tr'):
                                cols = row.find_all('td')
                                if len(cols) > 1:
                                    ip, port = cols[0].text.strip(), cols[1].text.strip()
                                    self.proxies.add(Proxy(f"{ip}:{port}", proxy_type))
            except Exception as e:
                logger.error(f"Failed to fetch proxies from {url}: {e}")

    async def gather_proxies(self, test_url="http://httpbin.org/get"):
        tasks = [self.fetch_proxies(source) for source in self.sources]
        await asyncio.gather(*tasks)
        logger.info(f"Collected {len(self.proxies)} raw proxies.")
        return await self.check_proxies(test_url)

    async def check_proxies(self, test_url, threads=300, timeout=4):
        logger.info("Checking proxies with advanced timeout...")
        loop = asyncio.get_event_loop()
        checked = await loop.run_in_executor(None, ProxyChecker.checkAll, self.proxies, timeout, threads, test_url)
        self.proxies = set(checked)
        logger.info(f"Found {len(self.proxies)} working proxies.")
        return self.proxies