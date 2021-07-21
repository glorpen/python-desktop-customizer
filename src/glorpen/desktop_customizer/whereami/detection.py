import asyncio
import logging
import platform
import socket
import typing

from glorpen.desktop_customizer.whereami.hints import Hint
from glorpen.desktop_customizer.whereami.hints.simple import HostHint, WifiHint
from glorpen.desktop_customizer.whereami.hints.xrand import ScreenHint, MonitorHint
from glorpen.desktop_customizer.whereami.wifi import WifiFinder
from glorpen.desktop_customizer.whereami.xrand import Detector


class _Listener(object):
    subscribed_keys: typing.Sequence[typing.Type[Hint]]
    callback: typing.Callable


class DetectionInfo(object):
    KEYS = [
        HostHint,
        ScreenHint,
        MonitorHint,
        WifiHint
    ]

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)

        self.data: typing.Dict[typing.Type[Hint], typing.Any] = {}
        self.listeners: typing.Dict[typing.Type[Hint], typing.List[_Listener]] = dict((i, []) for i in self.KEYS)

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
            self.update_key(HostHint, self.hostname())
        )

    async def update_key(self, k: typing.Type[Hint], v):
        self.data[k] = v

        self.logger.debug("Updated key %r", k)

        tasks = []
        for cb_info in self.listeners.get(k, []):
            try:
                args = [self.data[cb_k] for cb_k in cb_info.subscribed_keys]
            except KeyError:
                # not all required detectors are initialized
                continue
            tasks.append(cb_info.callback(*args))

        await asyncio.gather(*tasks)

    async def watch_wifi(self):
        last_info = {}
        async for info in self._wifi.poll():
            if info != last_info:
                last_info = info
                await self.update_key(WifiHint, info)

    async def watch_xrand(self):
        async for t, info in self._xrand.watch():
            await self.update_key(t, info)

    @classmethod
    def hostname(cls):
        info = HostHint()
        info.platform = platform.node()
        info.sock = socket.gethostname()
        return info

    def add_listener(self, keys, cb):
        for k in keys:
            listener = _Listener()
            listener.subscribed_keys = tuple(keys)
            listener.callback = cb
            self.listeners[k].append(listener)
