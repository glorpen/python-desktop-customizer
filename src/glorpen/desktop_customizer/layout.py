import xcffib
import xcffib.xproto

import xcffib.randr
conn = xcffib.connect(os.environ.get("DISPLAY"))
ext_r = conn(xcffib.randr.key)

root = conn.get_setup().roots[0].root

def _get_atom_id(name):
    return conn.core.InternAtom(False, len(name), name).reply().atom

ATOM_EDID = _get_atom_id("EDID")

# import pdb
# pdb.set_trace()

import pyedid.edid
import pyedid.helpers.registry
import time

reg = pyedid.helpers.registry.Registry()

screen_resources = ext_r.GetScreenResources(root).reply()
screen_modes = dict((m.id, m) for m in screen_resources.modes)

# TODO: grab server when changing stuff to accumulate events
conn.core.GrabServer()

# for monitor in ext_r.GetMonitors(root, 1).reply().monitors:
    # name = conn.core.GetAtomName(monitor.name).reply().name.raw.decode()
for output in screen_resources.outputs:
    output_info = ext_r.GetOutputInfo(output, 0).reply()
    
    # skip outputs without monitors
    if output_info.connection != 0:
        continue
    
    print(output_info.__dict__)
    # 32 as in 32 * uin32 = 128 edid bytes
    d = bytes(ext_r.GetOutputProperty(output, ATOM_EDID, xcffib.xproto.Atom.Any, 0, 32, False, False).reply().data)
    e = pyedid.edid.Edid(d, reg)
    print(e.serial, e.name)
    #print(bytes(r.data))
    
    # TODO: find crtc when screen is disabled
    print(output_info.crtc)

    crtc_info = None
    crtc = None
    crtc_outputs = []

    if output_info.crtc:
        crtc = output_info.crtc
        crtc_outputs.append(output)
    else:
        for crtc_id in output_info.crtcs:
            crtc_info = ext_r.GetCrtcInfo(crtc_id, 0).reply()
            # TODO: more checking if crt is usable
            if crtc_info.num_outputs == 0 and output in crtc_info.possible.list:
                crtc = crtc_id
                crtc_outputs.append(output)
                break
        # error if not crtc found?
    
    # TODO: disable unused crtcs (empty mode, no outputs)
    # TODO: calculate ScreenSize
    # TODO: calculate physical size
    ext_r.SetScreenSize(root, 6000, 3840, 1100, 527)

    ts = int(time.time())
    # xcffib.randr.Rotation.Rotate_270
    # xcffib.randr.Rotation.Rotate_0
    
    rotation = xcffib.randr.Rotation.Rotate_0
    primary = False
    pos = [0, 0]
    mode = None
    

    preferred_modes = [screen_modes[i] for i in output_info.modes[0:output_info.num_preferred]]

    if e.serial == "xxxx":
        rotation = xcffib.randr.Rotation.Rotate_90
        pos = [3840, 0]
        # print(crtc_info.__dict__)
        # print(output_info.__dict__)
    else:
        primary = True
        pos = [0, 960]
    

# --output DisplayPort-1 --mode 3840x2160 --rotate left --pos 3840x0 \
# --output DisplayPort-0 --mode 3840x2160 --pos 0x960 --primary
    # TODO: transform? width/height of rotated monitor

    # print(crtc_info)

    z = ext_r.SetCrtcConfig(
        crtc,
        ts,
        ts, # crtc_info.timestamp,
        pos[0],
        pos[1],
        preferred_modes[0].id,
        rotation,
        len(crtc_outputs),
        crtc_outputs
    ).reply()

    if primary:
        ext_r.SetOutputPrimary(root, output)

    # print(z.status)
    #xcffib.randr.Rotation

conn.flush()
conn.core.UngrabServer()
conn.disconnect()
