import os
import xcffib
import xcffib.xproto
import pyedid.edid
import pyedid.helpers.registry
import time
import xcffib.randr

class EdidReader(object):
    def __init__(self):
        super()

        self.reg = pyedid.helpers.registry.Registry()
        # TODO: read pci.ids

    def parse(self, data):
        return pyedid.edid.Edid(data, self.reg)


class LayoutManager(object):
    def _get_atom_id(self, name):
        return self.conn.core.InternAtom(False, len(name), name).reply().atom
    
    def __init__(self):
        super()
        self.edid = EdidReader()

    def connect(self):
        self.conn = xcffib.connect(os.environ.get("DISPLAY"))
        self.ext_r = self.conn(xcffib.randr.key)
        
        self._ATOM_EDID = self._get_atom_id("EDID")

    def get_edid_for_output(self, output):
        # 32 as in 32 * uin32 = 128 edid bytes
        d = bytes(self.ext_r.GetOutputProperty(output, self._ATOM_EDID, xcffib.xproto.Atom.Any, 0, 32, False, False).reply().data)
        return self.edid.parse(d)
    
    def get_crt_for_output(self, output, output_info):
        for crtc in output_info.crtcs:
            crtc_info = self.ext_r.GetCrtcInfo(crtc, 0).reply()
            # TODO: more checking if crt is usable
            if crtc_info.num_outputs == 0 and output in crtc_info.possible.list:
                return crtc
        # error if no crtc found?

    def apply(self):
        root = self.conn.get_setup().roots[0].root

        screen_resources = self.ext_r.GetScreenResources(root).reply()
        screen_modes = dict((m.id, m) for m in screen_resources.modes)

        screen_size = [0,0]
        screen_dimensions = [0,0]

        # grab server when changing stuff to accumulate events
        self.conn.core.GrabServer()

        for output in screen_resources.outputs:
            output_info = self.ext_r.GetOutputInfo(output, 0).reply()
            
            rotation = xcffib.randr.Rotation.Rotate_0
            primary = False
            pos = [0, 0]
            mode = 0
            matched = False
            crtc = None

            # skip outputs without monitors
            if output_info.connection == 0:
                e = self.get_edid_for_output(output)

                if e.name == "CB240HYK":
                    rotation = xcffib.randr.Rotation.Rotate_90
                    pos = [3840, 0]
                    matched = True
                elif e.name == "XV273K":
                    # screen_dimensions[0] += output_info.mm_width
                    # screen_dimensions[1] += output_info.mm_height
                    
                    # preferred_modes[0]

                    primary = True
                    pos = [0, 960]
                    matched = True
                
                if matched:
                    preferred_modes = [screen_modes[i] for i in output_info.modes[0:output_info.num_preferred]]
                    mode = preferred_modes[0].id

            # 0 is NULL
            if output_info.crtc > 0:
                crtc = output_info.crtc
            elif matched:
                crtc = self.get_crt_for_output(output, output_info)

            crtc_outputs = []
            if matched:
                crtc_outputs.append(output)

            if crtc is not None:
                self.ext_r.SetCrtcConfig(
                    crtc,
                    0,
                    0,
                    pos[0],
                    pos[1],
                    mode,
                    rotation,
                    len(crtc_outputs),
                    crtc_outputs
                ).reply()

            if primary:
                self.ext_r.SetOutputPrimary(root, output)

            # print(z.status)
            #xcffib.randr.Rotation

        # TODO: calculate ScreenSize
        # TODO: calculate physical size
        self.ext_r.SetScreenSize(root, 6000, 3840, 1100, 527)

        self.conn.flush()
        self.conn.core.UngrabServer()
        self.conn.disconnect()

l = LayoutManager()
l.connect()
l.apply()
