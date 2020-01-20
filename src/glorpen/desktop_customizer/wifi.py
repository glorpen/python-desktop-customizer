import asyncio
import logging
import netlink
import netlink.core
import netlink.genl
import netlink.genl.capi

NL80211_CMD_GET_INTERFACE = 5

NL80211_ATTR_IFNAME = 4
NL80211_ATTR_MAC = 6
NL80211_ATTR_SSID = 52

NL80211_ATTR_MAX = NL80211_ATTR_SSID

class DumpInterfacesMessage(netlink.core.Message):
    def __init__(self, family):
        super().__init__()
        netlink.genl.capi.genlmsg_put(self._msg, netlink.core.NL_AUTO_PORT, netlink.core.NL_AUTO_SEQ, family, 0, netlink.core.NLM_F_DUMP, NL80211_CMD_GET_INTERFACE, 0)

class WifiFinder(object):
    running = False

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)

    def nl_message_handler(self, msg, ctx):
        info = {}
        _e, attr = netlink.genl.capi.py_genlmsg_parse(netlink.capi.nlmsg_hdr(msg), 0, NL80211_ATTR_MAX, None)
        if NL80211_ATTR_IFNAME in attr:
            info["ifname"] = netlink.capi.nla_get_string(attr[NL80211_ATTR_IFNAME])
            if NL80211_ATTR_SSID in attr:
                info["ssid"] = netlink.capi.nla_get_string(attr[NL80211_ATTR_SSID])
            if NL80211_ATTR_MAC in attr:
                info["mac"] = netlink.capi.nla_data(attr[NL80211_ATTR_MAC]).hex()
        
        if info:
            ctx.append(info)

        return netlink.capi.NL_OK
    
    def connect(self):
        self._infos = []
        self._cb = netlink.core.Callback()
        self._cb.set_type(netlink.capi.NL_CB_VALID, netlink.capi.NL_CB_CUSTOM, self.nl_message_handler, self._infos)
        self._sk = netlink.core.Socket()
        self._sk.connect(netlink.core.NETLINK_GENERIC)

        self._msg_family = netlink.genl.capi.genl_ctrl_resolve(self._sk._sock, "nl80211")
        
        self.running = True
    
    def query(self):
        self._infos.clear()
        self._sk.send_auto_complete(DumpInterfacesMessage(self._msg_family))
        self._sk.recvmsgs(self._cb)
        return tuple(self._infos)

    def disconnect(self):
        self.running = False
        self._sk.disconnect()
    
    async def poll(self):
        while self.running:
            try:
                info = self.query()
                yield info
                await asyncio.sleep(3)
            except Exception as e:
                self.logger.exception(e)
                break
