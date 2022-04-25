import asyncio
import dataclasses
import datetime
import logging
import os
import typing

import pyedid
import xcffib
import xcffib.randr
import xcffib.xproto

from glorpen.desktop_customizer.whereami.hints import MonitorHint, ScreenHint, Position, Size


def get_atom_id(con, name):
    return con.core.InternAtom(False, len(name), name).reply().atom


def create_monitor_hint(output_info, edid: typing.Optional[pyedid.types.Edid]):
    return MonitorHint(
        output_name=output_info.name.raw.decode(),
        monitor_name=edid.name if edid else None,
        monitor_serial=edid.serial if edid else None,
        width_mm=output_info.mm_width,
        height_mm=output_info.mm_height,
        screen=None
    )


def rotation_to_degrees(r: int):
    if r & xcffib.randr.Rotation.Rotate_0:
        return 0
    if r & xcffib.randr.Rotation.Rotate_90:
        return 90
    if r & xcffib.randr.Rotation.Rotate_180:
        return 180
    if r & xcffib.randr.Rotation.Rotate_270:
        return 270
    raise Exception("Bad rotation")


def create_screen_hint(crtc_info):
    return ScreenHint(
        position=Position(crtc_info.x, crtc_info.y),
        size=Size(crtc_info.width, crtc_info.height),
        rotation=rotation_to_degrees(crtc_info.rotation),
    )


@dataclasses.dataclass
class MonitorInfo:
    output: int
    hint: MonitorHint

_MonitorDict = typing.Dict[int, MonitorInfo]

class MonitorDetector(object):
    running = False
    batch_changes_seconds = 1

    _root: int
    _conn: xcffib.Connection
    _ext_r: xcffib.randr.randrExtension
    _ATOM_EDID: int

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)

        self._physical_info = {}
        self._output_info = {}
        self._pending_changes = {
            MonitorHint: False,
            ScreenHint: False
        }

    def connect(self):
        self.running = True
        self._conn = xcffib.connect(os.environ.get("DISPLAY"))
        self._ext_r = self._conn(xcffib.randr.key)

        self._ATOM_EDID = get_atom_id(self._conn, "EDID")

        self._root = self._conn.get_setup().roots[0].root

    def disconnect(self):
        self.running = False
        self._conn.disconnect()

    def get_edid_for_output(self, output) -> pyedid.types.Edid:
        # 32 as in 32 * uin32 = 128 edid bytes
        d = bytes(self._ext_r.GetOutputProperty(
            output, self._ATOM_EDID, xcffib.xproto.Atom.Any, 0, 32, False, False
        ).reply().data)

        return pyedid.parse_edid(d)

    def query(self):
        screen_resources = self._ext_r.GetScreenResources(self._root).reply()

        for output in screen_resources.outputs:
            output_info = self._ext_r.GetOutputInfo(output, 0).reply()

            edid = None
            if output_info.connection == xcffib.randr.Connection.Connected:
                # no monitors
                edid = self.get_edid_for_output(output)

            physical_info = create_monitor_hint(output_info, edid)
            # self._physical_info[output] = physical_info

            if output_info.crtc > 0:
                crtc_info = self._ext_r.GetCrtcInfo(output_info.crtc, 0).reply()
                physical_info.screen = create_screen_hint(crtc_info)
                # self._output_info[output] = screen_info

            yield MonitorInfo(output=output, hint=physical_info)

    async def handle_event(self, ev, items: _MonitorDict):
        # self.logger.debug(ev.__dict__)
        if not isinstance(ev, xcffib.randr.NotifyEvent):
            self.logger.debug("Got %r event", ev)
            return

        elif ev.subCode == xcffib.randr.Notify.OutputChange:
            self.logger.debug("Output was changed")
            is_connected = ev.u.oc.connection == xcffib.randr.Connection.Connected
            output = ev.u.oc.output
            crtc = ev.u.oc.crtc
            # rotation = ev.u.oc.rotation

            e = self.get_edid_for_output(output) if is_connected else None
            output_info = self._ext_r.GetOutputInfo(output, 0).reply()

            pi = create_monitor_hint(output_info, e)

            if is_connected:
                # self.update_infos(output, pi, None)

                if crtc > 0 and ev.u.oc.mode > 0:
                    crtc_info = self._ext_r.GetCrtcInfo(output_info.crtc, 0).reply()
                    pi.screen = create_screen_hint(crtc_info)

            items[output] = MonitorInfo(output=output, hint=pi)
            return items

        elif ev.subCode == xcffib.randr.Notify.CrtcChange:
            self.logger.debug("Crtc was changed")
            crtc_info = self._ext_r.GetCrtcInfo(ev.u.cc.crtc, 0).reply()
            if ev.u.cc.mode > 0:
                for output in crtc_info.outputs:
                    items[output].hint.screen = create_screen_hint(crtc_info)
            else:
                for output in crtc_info.outputs:
                    items[output].hint.screen = None

            return items

    async def watch(self, interval: datetime.timedelta):
        self.connect()

        items = dict((m.output, m) for m in self.query())

        yield tuple(items.values())
        # yield (MonitorHint, self._physical_info)
        # yield (ScreenHint, self._output_info)

        self._ext_r.SelectInput(
            self._root,
            xcffib.randr.NotifyMask.OutputChange |
            xcffib.randr.NotifyMask.CrtcChange
        )
        self._conn.flush()

        # loop = asyncio.get_event_loop()
        # changes_timer = None

        while self.running:
            while True:
                ev = self._conn.poll_for_event()
                if ev is None:
                    break

                items = await self.handle_event(ev, items)
                yield tuple(items.values())

            await asyncio.sleep(interval.total_seconds())
