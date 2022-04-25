import asyncio
import dataclasses
import logging
import typing
from datetime import timedelta

import aiostream.stream

from glorpen.desktop_customizer.whereami.hints import HostHint, MonitorHint, WifiHint
from glorpen.desktop_customizer.whereami.host import hostname
from glorpen.desktop_customizer.whereami.wifi import WifiFinder
from glorpen.desktop_customizer.whereami.xrand import MonitorDetector

Z = typing.Type['Z']


@dataclasses.dataclass
class DetectionEvent:
    trigger: typing.Optional[type[Z]]
    state: typing.Dict[type[Z], Z]


class DetectionInfo(object):

    def __init__(
            self,
            xrand_interval: timedelta = timedelta(seconds=5),
            wifi_interval: timedelta = timedelta(seconds=10),
    ):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)

        self._cache = {
            HostHint: None,
            MonitorHint: None,
            WifiHint: None,
        }

        self._xrand_interval = xrand_interval
        self._wifi_interval = wifi_interval

        self._wifi = WifiFinder()
        self._xrand = MonitorDetector()

    def start(self):
        self._wifi.connect()
        self._xrand.connect()

    def stop(self):
        self._wifi.disconnect()
        self._xrand.disconnect()

    def query(self):
        return tuple(self._wifi.query()), tuple(self._xrand.query()), hostname()

    async def watch(self, bootstrap_timeout: timedelta = timedelta(seconds=5)):
        self._cache[HostHint] = hostname()

        async def gate():
            await asyncio.sleep(bootstrap_timeout.total_seconds())
            yield None

        z = aiostream.stream.merge(
            self._watch_wifi(),
            self._watch_xrand(),
            gate()
        )

        async with z.stream() as streamer:
            bootstrapped = False
            async for trigger in streamer:
                if not bootstrapped and trigger is None:
                    bootstrapped = True
                if bootstrapped:
                    yield DetectionEvent(
                        trigger=trigger,
                        state=self._cache
                    )

    async def _watch_wifi(self):
        async for info in self._wifi.poll(self._wifi_interval):
            self._cache[WifiHint] = info
            yield WifiHint

    async def _watch_xrand(self):
        async for info in self._xrand.watch(self._xrand_interval):
            self._cache[MonitorHint] = info
            yield MonitorHint
