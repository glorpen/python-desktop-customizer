from glorpen.desktop_customizer.whereami.hints import Hint

class HostnameHint(Hint):
    platform = None
    sock = None

class WifiHint(Hint):
    ifname = None
    ssid = None
    mac = None
