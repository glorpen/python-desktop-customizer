import platform
import socket
import asyncio
import logging

from glorpen.desktop_customizer.wifi import WifiFinder

class DetectionInfo(object):
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)

        self.data = {}
        self.listeners = {}

        self._wifi = WifiFinder()
    
    def start(self):
        self._wifi.connect()
    
    def stop(self):
        self._wifi.disconnect()
    
    async def watch(self):
        await asyncio.gather(
            self.watch_wifi(),
            self.update_key("hostname", self.hostname())
        )
    
    async def update_key(self, k, v):
        self.data[k] = v

        self.logger.debug("Updated key %r", k)

        tasks = []
        for l in self.listeners.get(k, []):
            tasks.append(l(self.data))
        
        await asyncio.gather(*tasks)

    async def watch_wifi(self):
        last_info = {}
        async for info in self._wifi.poll():
            if info != last_info:
                last_info = info
                await self.update_key("wifi", info)
    
    async def watch_monitors(self):
        pass
    
    async def watch_layout(self):
        pass

    def hostname(self):
        return {
            "platform": platform.node(),
            "sock": socket.gethostname()
        }
    
    def add_listener(self, keys, cb):
        for k in keys:
            self.listeners[k].append(cb)

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    d = DetectionInfo()
    d.start()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(d.watch())
    # eventy jako loop.call_soon ?
