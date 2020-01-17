import os
import xcffib
import xcffib.xproto
import pyedid.edid
import pyedid.helpers.registry
import time
import xcffib.randr
import logging

class EdidReader(object):
    def __init__(self):
        super().__init__()

        self.reg = pyedid.helpers.registry.Registry()
        # TODO: read pci.ids

    def parse(self, data):
        return pyedid.edid.Edid(data, self.reg)

class LayoutHint(object):
    edid_name = None
    edid_serial = None
    width = None
    height = None
    output_name = None
    output = None


class LayoutManager(object):
    def _get_atom_id(self, name):
        return self.conn.core.InternAtom(False, len(name), name).reply().atom
    
    def __init__(self):
        super().__init__()
        self.edid = EdidReader()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.layouts = []
    
    def add_layout(self, layout):
        self.layouts.append(layout)

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
        self.logger.debug("Disabling crtc %r", crtc)
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
    
    def disable_crtcs(self, crtcs):
        for crtc in crtcs:
            self.disable_crtc(crtc)
    
    def get_screen_sizes(self, outputs_data):
        """Returns max width and height in pixels and
        approximate physical width and height for whole screen"""
        max_x = max_y = 0
        dim_ratio = 0
        for output_data in outputs_data:
            sizing = ["width", "height"]
            
            if output_data["placement"].rotation in (xcffib.randr.Rotation.Rotate_90, xcffib.randr.Rotation.Rotate_270):
                sizing.reverse()

            x = output_data["placement"].position[0] + output_data["mode"][sizing[0]]
            y = output_data["placement"].position[1] + output_data["mode"][sizing[1]]

            max_x = max(x, max_x)
            max_y = max(y, max_y)

            if output_data["placement"].primary:
                # it probably doesn't matter so just use "DPI" from primary monitor
                dim_ratio = output_data["info"].mm_height / output_data["mode"]["height"]
        
        return max_x, max_y, int(max_x * dim_ratio), int(max_y * dim_ratio)

    def gather_output_data(self, screen_resources):
        screen_modes = dict((m.id, m) for m in screen_resources.modes)

        outputs_data = []
        for output in screen_resources.outputs:
            output_info = self.ext_r.GetOutputInfo(output, 0).reply()
            
            # skip outputs without monitors
            if output_info.connection == 0:
                e = self.get_edid_for_output(output)

                # output_info.num_preferred means modes[0:num]
                # preferred_modes = [screen_modes[i] for i in output_info.modes[0:output_info.num_preferred]]
                # mode = preferred_modes[0].id
                mode = screen_modes[output_info.modes[0]]

                outputs_data.append({
                    "edid": e,
                    "info": output_info,
                    "output": output,
                    "name": output_info.name.raw.decode(),
                    "mode": {
                        "id": mode.id,
                        "width": mode.width,
                        "height": mode.height,
                    }
                })
        return outputs_data
    
    def get_layout_hints(self, outputs_data):
        hints = []
        for od in outputs_data:
            h = LayoutHint()
            h.edid_name = od["edid"].name
            h.edid_serial = od["edid"].serial
            h.width = od["mode"]["width"]
            h.height = od["mode"]["height"]
            h.output = od["output"]
            h.output_name = od["name"]

            hints.append(h)
        return hints
    
    def find_layout(self, outputs_data):
        hints = self.get_layout_hints(outputs_data)

        for l in self.layouts:
            if l.fit(hints):
                return l

    def get_configs_for_layout(self, layout, outputs_data):
        crtcs_to_disable = []
        outputs_to_update = []

        for od in outputs_data:
            output = od["output"]
            output_info = od["info"]

            placement = layout.get_placement_for_output(output)
            
            if placement:
                info = {
                    "placement": placement
                }
                info.update(od)
                outputs_to_update.append(info)
            else:
                # mark for disabling only currently used crtc
                if output_info.crtc > 0: # 0 is NULL
                    crtcs_to_disable.append(output_info.crtc)
        
        return [
            crtcs_to_disable,
            outputs_to_update
        ]

    def apply_crtc_configs(self, outputs_to_update, root):
        self.logger.debug("Updating crtcs")
        for output_data in outputs_to_update:
            output_info = output_data["info"]
            placement = output_data["placement"]

            crtc = output_info.crtc if output_info.crtc > 0 else None
            if crtc is None:
                crtc = self.get_crt_for_output(output_data["output"])

                if crtc is None:
                    raise Exception("No crtc found for output %s" % output_data["name"])
            
            crtc_outputs = [output_data["output"]]

            self.ext_r.SetCrtcConfig(
                crtc,
                0,
                0,
                placement.position[0],
                placement.position[1],
                output_data["mode"]["id"],
                placement.rotation,
                len(crtc_outputs),
                crtc_outputs
            ).reply()

            if placement.primary:
                self.logger.debug("Setting primary output to %s", output_data["name"])
                self.ext_r.SetOutputPrimary(root, output_data["output"])

        max_x, max_y, dim_x, dim_y = self.get_screen_sizes(outputs_to_update)
        self.logger.debug("Setting screen size to %dx%d (%dmm x %dmm)", max_x, max_y, dim_x, dim_y)
        self.ext_r.SetScreenSize(root, max_x, max_y, dim_x, dim_y)

        self.conn.flush()


    def apply(self):
        root = self.conn.get_setup().roots[0].root

        # grab server when changing stuff to accumulate events
        self.logger.debug("Grabbing server")
        self.conn.core.GrabServer()

        try:
            screen_resources = self.ext_r.GetScreenResources(root).reply()
            outputs_data = self.gather_output_data(screen_resources)
            layout = self.find_layout(outputs_data)

            if layout:
                crtcs_to_disable, outputs_to_update = self.get_configs_for_layout(layout, outputs_data)
                self.disable_crtcs(crtcs_to_disable)
                self.apply_crtc_configs(outputs_to_update, root)
            else:
                self.logger.warning("No layout found")
        finally:
            self.logger.debug("Ungrabbing server")
            self.conn.core.UngrabServer()

            self.conn.disconnect()

class Placement(object):
    primary = False
    rotation = xcffib.randr.Rotation.Rotate_0
    
    def __init__(self, **kwargs):
        super().__init__()
        self.position = [0, 0]

        self.__dict__.update(kwargs)
    
class Layout(object):
    def __init__(self):
        super().__init__()

    def fit(self, hints):
        return False
    
    def get_placement_for_output(self, output):
        raise NotImplementedError()

class ExampleLayout(Layout):

    mon_right = Placement(
        rotation=xcffib.randr.Rotation.Rotate_90,
        position=[3840, 0]
    )
    mon_main = Placement(
        primary=True,
        position=[0, 960]
    )

    def fit(self, hints):
        ret = {}
        for hint in hints:
            if hint.edid_name == "CB240HYK":
                ret["right"] = hint.output
            elif hint.edid_name == "XV273K":
                ret["main"] = hint.output
        
        self.detection_info = ret

        return len(ret) == 2


    def get_placement_for_output(self, output):
        if self.detection_info["main"] == output:
            return self.mon_main
        elif self.detection_info["right"] == output:
            return self.mon_right


logging.basicConfig(level=logging.DEBUG)

sl = ExampleLayout()

l = LayoutManager()
l.add_layout(sl)
l.connect()
l.apply()
