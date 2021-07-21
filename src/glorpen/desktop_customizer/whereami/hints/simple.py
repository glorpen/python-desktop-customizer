from glorpen.desktop_customizer.whereami.hints import Hint


class HostHint(Hint):
    platform = None
    sock = None


class WifiHint(Hint):
    ifname = None
    ssid = None
    mac = None
