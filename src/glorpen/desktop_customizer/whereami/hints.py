import dataclasses
import typing


@dataclasses.dataclass
class HostHint:
    platform: str
    sock: str


@dataclasses.dataclass
class WifiHint:
    ifname: str
    ssid: typing.Optional[str]
    mac: typing.Optional[str]

@dataclasses.dataclass
class Position:
    x: int
    y: int

@dataclasses.dataclass
class Size:
    width: int
    height: int

@dataclasses.dataclass
class ScreenHint:
    position: Position
    size: Size
    rotation: int

    @property
    def x(self):
        return self.position[0] if self.position else None

    @property
    def y(self):
        return self.position[1] if self.position else None

    @property
    def width(self):
        return self.size[0] if self.size else None

    @property
    def height(self):
        return self.size[1] if self.size else None


@dataclasses.dataclass
class MonitorHint:
    output_name: str
    width_mm: int
    height_mm: int
    monitor_name: typing.Optional[str]
    monitor_serial: typing.Optional[str]

    screen: typing.Optional[ScreenHint]
