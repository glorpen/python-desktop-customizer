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
    
    def get_crt_for_output(self, output, output_info = None):
        if output_info is None:
            output_info = self.ext_r.GetOutputInfo(output, 0).reply()
        
        for crtc in output_info.crtcs:
            crtc_info = self.ext_r.GetCrtcInfo(crtc, 0).reply()
            # TODO: more checking if crt is usable
            if crtc_info.num_outputs == 0 and output in crtc_info.possible.list:
                return crtc
        # error if no crtc found?

    def disable_crtc(self, crtc):
        self.ext_r.SetCrtcConfig(
            crtc,
            0,
            0,
            0,
            0,
            0,
            xcffib.randr.Rotation.Rotate_0,
            0,
            []
        ).reply()
    
    def get_screen_sizes(self, crtc_infos):
        """Returns max width and height in pixels and
        approximate physical width and height for whole screen"""
        max_x = max_y = 0
        dim_ratio = 0
        for info in crtc_infos:
            sizing = ["width", "height"]
            
            if info["rotation"] in (xcffib.randr.Rotation.Rotate_90, xcffib.randr.Rotation.Rotate_270):
                sizing.reverse()

            x = info["pos"][0] + info["mode"][sizing[0]]
            y = info["pos"][1] + info["mode"][sizing[1]]

            max_x = max(x, max_x)
            max_y = max(y, max_y)

            if info["primary"]:
                dim_ratio = info["dimensions"]["height"] / info["mode"]["height"]
        
        return max_x, max_y, int(max_x * dim_ratio), int(max_y * dim_ratio)

    def apply(self):
        root = self.conn.get_setup().roots[0].root

        screen_resources = self.ext_r.GetScreenResources(root).reply()
        screen_modes = dict((m.id, m) for m in screen_resources.modes)

        crtcs_to_disable = []
        outputs_to_update = []

        # grab server when changing stuff to accumulate events
        self.conn.core.GrabServer()

        # TODO: order: turn off crts, set screen size, configure crts, set primary

        for output in screen_resources.outputs:
            output_info = self.ext_r.GetOutputInfo(output, 0).reply()
            
            rotation = xcffib.randr.Rotation.Rotate_0
            primary = False
            pos = [0, 0]
            mode = 0
            matched = False

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
                    # output_info.num_preferred means modes[0:num]
                    # preferred_modes = [screen_modes[i] for i in output_info.modes[0:output_info.num_preferred]]
                    # mode = preferred_modes[0].id

                    mode = screen_modes[output_info.modes[0]]

                    outputs_to_update.append({
                        "output": output,
                        "mode": {
                            "id": mode.id,
                            "width": mode.width,
                            "height": mode.height
                        },
                        "dimensions": {
                            "width": output_info.mm_width,
                            "height": output_info.mm_height,
                        },
                        "pos": pos,
                        "rotation": rotation,
                        "crtc": output_info.crtc if output_info.crtc > 0 else None,
                        "primary": primary
                    })
                else:
                    # 0 is NULL
                    if output_info.crtc > 0:
                        crtcs_to_disable.append(output_info.crtc)

        for crtc in crtcs_to_disable:
            self.disable_crtc(crtc)
        
        max_x, max_y, dim_x, dim_y = self.get_screen_sizes(outputs_to_update)
        self.ext_r.SetScreenSize(root, max_x, max_y, dim_x, dim_y)

        for info in outputs_to_update:
            crtc = info["crtc"]
            if crtc is None:
                crtc = self.get_crt_for_output(info["output"])
            crtc_outputs = [ info["output"] ]

            self.ext_r.SetCrtcConfig(
                crtc,
                0,
                0,
                info["pos"][0],
                info["pos"][1],
                info["mode"]["id"],
                info["rotation"],
                len(crtc_outputs),
                crtc_outputs
            ).reply()

            if info["primary"]:
                self.ext_r.SetOutputPrimary(root, info["output"])

        self.conn.flush()
        self.conn.core.UngrabServer()
        self.conn.disconnect()

l = LayoutManager()
l.connect()
l.apply()
