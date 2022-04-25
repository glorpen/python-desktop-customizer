import platform
import socket

from glorpen.desktop_customizer.whereami.hints import HostHint


def hostname():
    return HostHint(
        platform=platform.node(),
        sock=socket.gethostname()
    )
