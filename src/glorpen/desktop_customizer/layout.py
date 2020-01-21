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

def get_rotated_sizing(rotation, original_size):
    if rotation in (Rotation.Rotate_90, Rotation.Rotate_270):
        return (original_size[1], original_size[0])
    return tuple(original_size)

class LayoutHint(object):
    edid_name = None
    edid_serial = None
    width = None
    height = None
    output_name = None
    output = None

    def load_output_data(self, output_data):
        self.edid_name = output_data["edid"]["name"]
        self.edid_serial = output_data["edid"]["serial"]
        self.width = output_data["mode"]["width"]
        self.height = output_data["mode"]["height"]
        self.output = output_data["output"]
        self.output_name = output_data["name"]

        return self
    
    # def __repr__(self):
    #     return "<%s: %r>" % (self.__class__.__qualname__, self.__dict__)

class LayoutManager(object):
    def _get_atom_id(self, name):
        return self.conn.core.InternAtom(False, len(name), name).reply().atom
    
    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.layouts = []
    
    def add_layout(self, layout):
        self.layouts.append(layout)

    def connect(self):
        self.conn = xcffib.connect(os.environ.get("DISPLAY"))
        self.ext_r = self.conn(xcffib.randr.key)
    
    def disconnect(self):
        self.conn.disconnect()

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
            Rotation.Rotate_0,
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
            size = get_rotated_sizing(
                output_data["placement"].rotation,
                [
                    output_data["mode"]["width"],
                    output_data["mode"]["height"],
                ]
            )

            x = output_data["placement"].position[0] + size[0]
            y = output_data["placement"].position[1] + size[1]

            max_x = max(x, max_x)
            max_y = max(y, max_y)

            if output_data["placement"].primary:
                # it probably doesn't matter so just use "DPI" from primary monitor
                dim_ratio = output_data["info"]["mm_height"] / output_data["mode"]["height"]
        
        return max_x, max_y, int(max_x * dim_ratio), int(max_y * dim_ratio)

    def gather_output_data(self, screen_resources, hints):
        screen_modes = dict((m.id, m) for m in screen_resources.modes)

        outputs_data = []
        for output in screen_resources.outputs:
            output_info = self.ext_r.GetOutputInfo(output, 0).reply()
            
            # skip outputs without monitors
            if output_info.connection == 0:
                # output_info.num_preferred means modes[0:num]
                # preferred_modes = [screen_modes[i] for i in output_info.modes[0:output_info.num_preferred]]
                # mode = preferred_modes[0].id
                mode = screen_modes[output_info.modes[0]]

                outputs_data.append({
                    "edid": {
                        "name": hints[output].monitor_name,
                        "serial": hints[output].monitor_serial,
                    },
                    "info": {
                        "crtc": output_info.crtc if output_info.crtc > 0 else None, # 0 is NULL
                        "mm_height": hints[output].height_mm
                    },
                    "output": output,
                    "name": hints[output].output_name,
                    "mode": {
                        "id": mode.id,
                        "width": mode.width,
                        "height": mode.height,
                    }
                })
        return outputs_data
    
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
                if output_info["crtc"] is not None:
                    crtcs_to_disable.append(output_info["crtc"])
        
        return [
            crtcs_to_disable,
            outputs_to_update
        ]

    def apply_crtc_configs(self, outputs_to_update, root):
        self.logger.debug("Updating crtcs")
        for output_data in outputs_to_update:
            placement = output_data["placement"]

            crtc = output_data["info"]["crtc"]
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

    def get_hints_from_outputs_data(self, outputs_data):
        hints = []
        for od in outputs_data:
            h = LayoutHint().load_output_data(od)
            hints.append(h)
        return hints

    async def apply(self, hints):
        # configured_outputs = []

        root = self.conn.get_setup().roots[0].root

        # grab server when changing stuff to accumulate events
        self.logger.debug("Grabbing server")
        self.conn.core.GrabServer()

        try:
            screen_resources = self.ext_r.GetScreenResources(root).reply()
            outputs_data = self.gather_output_data(screen_resources, hints)
            layout_hints = self.get_hints_from_outputs_data(outputs_data)

            layout = None
            for l in self.layouts:
                if l.fit(layout_hints):
                    layout = l
                    break

            if layout:
                crtcs_to_disable, outputs_to_update = self.get_configs_for_layout(layout, outputs_data)
                self.disable_crtcs(crtcs_to_disable)
                self.apply_crtc_configs(outputs_to_update, root)
            else:
                self.logger.warning("No layout found")
        finally:
            self.conn.flush()
            self.logger.debug("Ungrabbing server")
            self.conn.core.UngrabServer()
            self.conn.flush()

            # self.conn.disconnect()

class Placement(object):
    primary = False
    rotation = Rotation.Rotate_0
    
    def __init__(self, **kwargs):
        super().__init__()
        self.position = [0, 0]

        self.__dict__.update(kwargs)
    
    def __repr__(self):
        return "<%s: %r>" % (self.__class__.__qualname__, self.__dict__)
    
class Layout(object):
    def __init__(self):
        super().__init__()

    def fit(self, layout_hints):
        return False
    
    def get_placement_for_output(self, output):
        raise NotImplementedError()
