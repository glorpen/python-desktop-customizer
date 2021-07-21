import asyncio
import logging
import os
import struct

import xcffib
import xcffib.randr
import xcffib.xproto

from glorpen.desktop_customizer.whereami.xrand import get_atom_id


# def get_atom_id(con, name):
#     return con.core.InternAtom(False, len(name), name).reply().atom

class Dimmer(object):
    running = False

    _known_fullscreen_window = None

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)

        self._original_gamma = {}

    def connect(self):
        self.running = True
        self.conn = xcffib.connect(os.environ.get("DISPLAY"))
        self.ext_r = self.conn(xcffib.randr.key)

        self._ATOM_NET_WM_STATE = get_atom_id(self.conn, "_NET_WM_STATE")
        self._ATOM_FULLSCREEN = get_atom_id(self.conn, "_NET_WM_STATE_FULLSCREEN")
        self._ATOM_FOCUSED = get_atom_id(self.conn, "_NET_WM_STATE_FOCUSED")
        self._ATOM_WM_STATE = get_atom_id(self.conn, "WM_STATE")

        self.root = self.conn.get_setup().roots[0].root

    def disconnect(self):
        self.running = False
        self.conn.disconnect()

    def _dim_crtc(self, crtc):
        if crtc in self._original_gamma:
            return

        org_gamma = self.ext_r.GetCrtcGamma(crtc).reply()
        self._original_gamma[crtc] = [
            org_gamma.size,
            org_gamma.red, org_gamma.green, org_gamma.blue
        ]
        colors = []

        for i in [org_gamma.red, org_gamma.green, org_gamma.blue]:
            tmp = []
            for j in i:
                tmp.append(int(j * 0.1))
            colors.append(tmp)

        # 'size', 'red', 'green', 'blue

        self.ext_r.SetCrtcGamma(crtc, org_gamma.size, *colors)
        # print("dim crtc")

    def _undim_crtc(self, crtc):
        if crtc not in self._original_gamma:
            return

        self.ext_r.SetCrtcGamma(crtc, *self._original_gamma.pop(crtc))

    def _undim_all(self):
        for crtc in list(self._original_gamma.keys()):
            self._undim_crtc(crtc)

    def dim_others(self, used_window):
        geo = self.conn.core.GetGeometry(used_window).reply()
        coords = self.conn.core.TranslateCoordinates(used_window, self.root, geo.x, geo.y).reply()

        x = coords.dst_x
        y = coords.dst_y

        window_resources = self.ext_r.GetScreenResources(self.root).reply()

        for output in window_resources.outputs:
            output_info = self.ext_r.GetOutputInfo(output, 0).reply()
            if output_info.crtc == 0:
                continue
            crtc_info = self.ext_r.GetCrtcInfo(output_info.crtc, 0).reply()
            # ret.rotation = crtc_info.rotation
            # print([crtc_info.x, crtc_info.y], [crtc_info.width, crtc_info.height])

            if crtc_info.x <= x < crtc_info.x + crtc_info.width and crtc_info.y <= y < crtc_info.y + crtc_info.height:
                self._undim_crtc(output_info.crtc)
            else:
                self._dim_crtc(output_info.crtc)
                # gamma_size = self.ext_r.GetCrtcGammaSize(output_info.crtc).reply().size

            # https://gitlab.freedesktop.org/xorg/app/xrandr/blob/master/xrandr.c#L1511
            # XRRSetCrtcGamma(dpy, crtc->crtc.xid, crtc_gamma);

    def get_fullscreen_window(self):
        return self._find_fullscreen(self.root)

    def _find_fullscreen(self, window):
        r = self.conn.core.QueryTree(window).reply()

        for w in r.children:
            d = self.conn.core.GetProperty(
                window=w, delete=False, type=xcffib.xproto.Atom.ATOM,
                property=self._ATOM_NET_WM_STATE, long_offset=0, long_length=4).reply()
            if d.length:
                z = b"".join(d.value)
                atoms = struct.unpack("I" * int(len(z) / 4), z)
                if {self._ATOM_FULLSCREEN, self._ATOM_FOCUSED}.issubset(atoms):
                    return w

            ret = self._find_fullscreen(w)
            if ret:
                return ret

    def is_fullscreen(self, window):
        try:
            d = self.conn.core.GetProperty(
                window=window, delete=False, type=xcffib.xproto.Atom.ATOM,
                property=self._ATOM_NET_WM_STATE, long_offset=0, long_length=4).reply()
        except xcffib.xproto.WindowError:
            return False

        if d.length:
            z = b"".join(d.value)
            atoms = struct.unpack("I" * int(len(z) / 4), z)
            return {self._ATOM_FULLSCREEN, self._ATOM_FOCUSED}.issubset(atoms)
        return False

    def _walk_windows(self, window, cb):
        try:
            r = self.conn.core.QueryTree(window).reply()
        except xcffib.xproto.WindowError:
            return

        d = self.conn.core.GetProperty(
            window=window, delete=False, type=xcffib.xproto.Atom.Any,
            property=self._ATOM_WM_STATE, long_offset=0, long_length=4).reply()
        # skip windows without WM_STATE property
        if not d.value:
            return

        for w in r.children:
            yield cb(w)
            self._walk_windows(w, cb)

    def _setup_events(self, window):
        def set_events(win):
            self.conn.core.ChangeWindowAttributes(
                win,
                value_mask=xcffib.xproto.CW.EventMask,
                value_list=[
                    xcffib.xproto.EventMask.PropertyChange | xcffib.xproto.EventMask.SubstructureNotify | xcffib.xproto.EventMask.StructureNotify
                ]
            )

        set_events(window)

        for dummy in self._walk_windows(window, set_events):
            pass

    def handle_window(self, window):
        if self.is_fullscreen(window):
            self._known_fullscreen_window = window
            self.dim_others(window)
        elif window == self._known_fullscreen_window:
            self._known_fullscreen_window = None
            self._undim_all()
        elif self._known_fullscreen_window:
            # not always reported that we are back on fs win
            if self.is_fullscreen(self._known_fullscreen_window):
                self.dim_others(self._known_fullscreen_window)
            else:
                # we are not fs window, so check if last fs win is still fs
                self._undim_all()

    async def loop(self):
        # return
        self._setup_events(self.root)

        while self.running:
            while True:
                try:
                    ev = self.conn.poll_for_event()
                except xcffib.xproto.WindowError as e:
                    break

                if ev is None:
                    break

                if isinstance(ev, xcffib.xproto.PropertyNotifyEvent):
                    self.logger.debug("Property:  window %d", ev.window)
                    self.handle_window(ev.window)
                elif isinstance(ev, xcffib.xproto.MapNotifyEvent):
                    self.logger.debug("MapNotify: window %d", ev.window)
                    self.handle_window(ev.window)
                elif isinstance(ev, xcffib.xproto.ConfigureNotifyEvent):
                    self.logger.debug("Configure: window %d", ev.window)
                    self.handle_window(ev.window)
                elif isinstance(ev, xcffib.xproto.DestroyNotifyEvent):
                    self.logger.debug("Configure: window %d", ev.window)
                    self.handle_window(ev.window)
                elif isinstance(ev, xcffib.xproto.CreateNotifyEvent):
                    self.logger.debug("CreateNotify: window %d", ev.window)
                    self._setup_events(ev.window)
                else:
                    self.logger.debug("Unhandled event %r", ev)

            await asyncio.sleep(0.2)
