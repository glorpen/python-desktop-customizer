import os
import xcffib
import xcffib.xproto
import pyedid.edid
import pyedid.helpers.registry
import time
import xcffib.randr
import logging
import asyncio

from xcffib.randr import Rotation
from glorpen.desktop_customizer.whereami.hints.xrand import MonitorHint, ScreenHint

class EdidReader(object):
    def __init__(self):
        super().__init__()

        self.reg = pyedid.helpers.registry.Registry()
        # TODO: read pci.ids

    def parse(self, data):
        return pyedid.edid.Edid(data, self.reg)

def get_atom_id(con, name):
    return con.core.InternAtom(False, len(name), name).reply().atom

class Detector(object):
    running = False
    batch_changes_seconds = 1

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.edid = EdidReader()

        self._physical_info = {}
        self._output_info = {}
        self._pending_changes = {
            MonitorHint: False,
            ScreenHint: False
        }

    def connect(self):
        self.running = True
        self.conn = xcffib.connect(os.environ.get("DISPLAY"))
        self.ext_r = self.conn(xcffib.randr.key)
        
        self._ATOM_EDID = get_atom_id(self.conn, "EDID")

        self.root = self.conn.get_setup().roots[0].root
    
    def disconnect(self):
        self.running = False
        self.conn.disconnect()

    def get_edid_for_output(self, output):
        # 32 as in 32 * uin32 = 128 edid bytes
        d = bytes(self.ext_r.GetOutputProperty(output, self._ATOM_EDID, xcffib.xproto.Atom.Any, 0, 32, False, False).reply().data)
        return self.edid.parse(d)

    def find_initial_state(self):
        screen_resources = self.ext_r.GetScreenResources(self.root).reply()

        self._output_info = {}
        self._physical_info = {}

        for output in screen_resources.outputs:
            output_info = self.ext_r.GetOutputInfo(output, 0).reply()
            
            # skip outputs without monitors
            if output_info.connection != xcffib.randr.Connection.Connected:
                continue
            
            edid = self.get_edid_for_output(output)

            physical_info = MonitorHint.create(output, output_info, edid)
            self._physical_info[output] = physical_info

            if output_info.crtc > 0:
                crtc_info = self.ext_r.GetCrtcInfo(output_info.crtc, 0).reply()
                screen_info = ScreenHint.create(physical_info, crtc_info)
                self._output_info[output] = screen_info

    def update_infos(self, output, physical, screen):
        if screen is False and self._output_info.pop(output, None):
            self._pending_changes[ScreenHint] = True
        if physical is False and self._physical_info.pop(output, None):
            self._pending_changes[MonitorHint] = True
        
        if screen and self._output_info.get(output, None) != screen:
            self._output_info[output] = screen
            self._pending_changes[ScreenHint] = True
        if physical and self._physical_info.get(output, None) != physical:
            self._physical_info[output] = physical
            self._pending_changes[MonitorHint] = True
        
    async def handle_event(self, ev):
        # self.logger.debug(ev.__dict__)
        if not isinstance(ev, xcffib.randr.NotifyEvent):
            self.logger.debug("Got %r event", ev)
            return
        
        if ev.subCode == xcffib.randr.Notify.OutputChange:
            self.logger.debug("Output was changed")
            is_connected = ev.u.oc.connection == xcffib.randr.Connection.Connected
            output = ev.u.oc.output
            crtc = ev.u.oc.crtc
            # rotation = ev.u.oc.rotation

            if is_connected:
                e = self.get_edid_for_output(output)
                output_info = self.ext_r.GetOutputInfo(output, 0).reply()
                
                pi = MonitorHint.create(output, output_info, e)
                self.update_infos(output, pi, None)
                
                if crtc > 0 and ev.u.oc.mode > 0:
                    crtc_info = self.ext_r.GetCrtcInfo(output_info.crtc, 0).reply()
                    screen_info = ScreenHint.create(self._physical_info[output], crtc_info)
                    self.update_infos(output, None, screen_info)
                else:
                    self.update_infos(output, None, False)
            else:
                self.update_infos(output, False, False)

        if ev.subCode == xcffib.randr.Notify.CrtcChange:
            self.logger.debug("Crtc was changed")
            crtc_info = self.ext_r.GetCrtcInfo(ev.u.cc.crtc, 0).reply()
            if ev.u.cc.mode > 0:
                for output in crtc_info.outputs:
                    screen_info = ScreenHint.create(self._physical_info[output], crtc_info)
                    self.update_infos(output, None, screen_info)
            else:
                for output in crtc_info.outputs:
                    self.update_infos(output, None, False)
    
    def has_pending_changes(self):
        for i in self._pending_changes.values():
            if i:
                return True
        return False
    
    async def watch(self):
        self.connect()

        self.find_initial_state()
        yield (MonitorHint, self._physical_info)
        yield (ScreenHint, self._output_info)

        self.ext_r.SelectInput(self.root,
            xcffib.randr.NotifyMask.OutputChange |
            xcffib.randr.NotifyMask.CrtcChange
        )
        self.conn.flush()

        loop = asyncio.get_event_loop()
        changes_timer = None

        while self.running:
            while True:
                ev = self.conn.poll_for_event()
                if ev is None:
                    break
                
                await self.handle_event(ev)
            
            if changes_timer is None and self.has_pending_changes():
                changes_timer = loop.time()
            
            if changes_timer is not None and changes_timer + self.batch_changes_seconds < loop.time():
                for i, info in [(MonitorHint, self._physical_info), (ScreenHint, self._output_info)]:
                    if self._pending_changes[i]:
                        self._pending_changes[i] = False
                        yield (i, info)
                changes_timer = None
            # TODO: make events run in batches, eg. max one per second?

            await asyncio.sleep(0.7)
