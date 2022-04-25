import asyncio
import datetime
import logging
import typing

from pr2modules.iwutil import IW

from glorpen.desktop_customizer.whereami.hints import WifiHint


class WifiFinder:
    _running = False
    _iw: typing.Optional[IW]

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)

    def query(self):
        for name, (index, phy, mac, _unknown1, _unknown2) in self._iw.get_interfaces_dict().items():
            for data in self._iw.get_interface_by_ifindex(index):
                attrs = dict(data["attrs"])
                yield WifiHint(
                    ssid=attrs.get('NL80211_ATTR_SSID', None),
                    mac=attrs.get('NL80211_ATTR_MAC', None),
                    ifname=name
                )

    def connect(self):
        self._iw = IW()
        self._running = True

    def disconnect(self):
        self._running = False
        self._iw.close()
        self._iw = None

    async def poll(self, interval: datetime.timedelta):
        last_data = None
        while self._running:
            try:
                data = tuple(self.query())
                if data != last_data:
                    last_data = data
                    yield data
                await asyncio.sleep(interval.total_seconds())
            except Exception as e:
                self.logger.exception(e)
                break
