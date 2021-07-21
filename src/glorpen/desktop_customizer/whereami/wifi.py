import asyncio
import logging

from glorpen.desktop_customizer.whereami.hints.simple import WifiHint
from pr2modules.iwutil import IW


class WifiFinder(object):
    running = False

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        self._iw = IW()

    def query(self):
        for name, (index, phy, mac, _unknown1, _unknown2) in self._iw.get_interfaces_dict().items():
            for data in self._iw.get_interface_by_ifindex(index):
                attrs = dict(data["attrs"])
                hint = WifiHint()
                hint.ssid = attrs.get('NL80211_ATTR_SSID', None)
                hint.mac = attrs.get('NL80211_ATTR_MAC', None)
                hint.ifname = name

                yield hint

    def connect(self):
        self.running = True

    def disconnect(self):
        self.running = False
        self._iw.close()

    async def poll(self):
        while self.running:
            try:
                for hint in self.query():
                    yield hint
                await asyncio.sleep(3)
            except Exception as e:
                self.logger.exception(e)
                break
