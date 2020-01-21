import platform
import socket
import asyncio
import logging

from glorpen.desktop_customizer.whereami.wifi import WifiFinder
from glorpen.desktop_customizer.whereami.xrand import Detector
from glorpen.desktop_customizer.whereami.hints.xrand import ScreenHint, MonitorHint
from glorpen.desktop_customizer.whereami.hints.simple import HostnameHint

class DetectionInfo(object):
    KEYS = [
        HostnameHint,
        ScreenHint,
        MonitorHint
    ]
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)

        self.data = {}
        self.listeners = dict((i, []) for i in self.KEYS)

        self._wifi = WifiFinder()
        self._xrand = Detector()
    
    def start(self):
        self._wifi.connect()
        self._xrand.connect()
    
    def stop(self):
        self._wifi.disconnect()
        self._xrand.disconnect()
    
    async def watch(self):
        await asyncio.gather(
            self.watch_wifi(),
            self.watch_xrand(),
            self.update_key(HostnameHint, self.hostname())
        )
    
    async def update_key(self, k, v):
        self.data[k] = v

        self.logger.debug("Updated key %r", k)

        tasks = []
        for l in self.listeners.get(k, []):
            tasks.append(l(v))
        
        await asyncio.gather(*tasks)

    async def watch_wifi(self):
        last_info = {}
        async for info in self._wifi.poll():
            if info != last_info:
                last_info = info
                await self.update_key("wifi", info)
    
    async def watch_xrand(self):
        async for t, info in self._xrand.watch():
            await self.update_key(t, info)
    
    def hostname(self):
        info = HostnameHint()
        info.platform = platform.node()
        info.sock = socket.gethostname()
        return info
    
    def add_listener(self, keys, cb):
        for k in keys:
            self.listeners[k].append(cb)
