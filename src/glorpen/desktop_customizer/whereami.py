import platform
import socket

NL80211_CMD_GET_INTERFACE = 5

NL80211_ATTR_IFNAME = 4
NL80211_ATTR_MAC = 6
NL80211_ATTR_SSID = 52

NL80211_ATTR_MAX = NL80211_ATTR_SSID


import netlink
import netlink.core
import netlink.genl
import netlink.genl.capi

class WifiFinder(object):

    def nl_message_handler(self, msg, ctx):
        info = {}
        _e, attr = netlink.genl.capi.py_genlmsg_parse(netlink.capi.nlmsg_hdr(msg), 0, NL80211_ATTR_MAX, None)
        if NL80211_ATTR_IFNAME in attr:
            info["ifname"] = netlink.capi.nla_data(attr[NL80211_ATTR_IFNAME])[:-1].decode()
            if NL80211_ATTR_SSID in attr:
                info["ssid"] = netlink.capi.nla_data(attr[NL80211_ATTR_SSID]).decode()
            if NL80211_ATTR_MAC in attr:
                info["mac"] = netlink.capi.nla_data(attr[NL80211_ATTR_MAC]).hex()
        
        if info:
            ctx.append(info)

        return netlink.capi.NL_OK

    def find(self):
        # sk = netlink.capi.nl_socket_alloc()
        cb = netlink.capi.nl_cb_alloc(netlink.capi.NL_CB_DEFAULT)
        # netlink.capi.nl_close()
        sk = netlink.capi.nl_socket_alloc_cb(cb)
        netlink.genl.capi.genl_connect(sk)
        
        family = netlink.genl.capi.genl_ctrl_resolve(sk, "nl80211")
        msg = netlink.capi.nlmsg_alloc()
        netlink.genl.capi.genlmsg_put(msg, 0, 0, family, 0, netlink.core.NLM_F_DUMP, NL80211_CMD_GET_INTERFACE, 0)

        wifi_interfaces = []

        netlink.core.capi.py_nl_cb_set(cb, netlink.capi.NL_CB_VALID, netlink.capi.NL_CB_CUSTOM, self.nl_message_handler, wifi_interfaces)
        netlink.capi.nl_send_auto_complete(sk, msg)

        netlink.capi.nl_recvmsgs(sk, cb)

        netlink.capi.nlmsg_free(msg)
        netlink.capi.nl_socket_free(sk)

        return wifi_interfaces

class DetectionInfo(object):
    def __init__(self):
        super().__init__()
        self._wifi = WifiFinder()
    
    def hostname(self):
        return {
            "platform": platform.node(),
            "sock": socket.gethostname()
        }
    
    def wifi(self):
        return self._wifi.find()
