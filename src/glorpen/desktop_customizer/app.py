#!/usr/bin/env python3

import xcffib
import xcffib.xproto
import xcffib.xinerama as xinerama
# import xcffib.bigreq as bigrequest
import os
import struct
import PIL
import PIL.Image
import PIL.ImageOps


# w = 1024
# h = 1024

# conn = xcffib.connect(display=os.environ.get("DISPLAY"))
# ext_x = conn(xinerama.key)
# # ext_b = conn(bigrequest.key)

# setup = conn.get_setup()

# def get_atom_id(name):
#     return conn.core.InternAtom(False, len(name), name).reply().atom

# _XROOTPMAP_ID = get_atom_id("_XROOTPMAP_ID")
# ESETROOT_PMAP_ID = get_atom_id("ESETROOT_PMAP_ID")

# XCB_CW_BACK_PIXMAP = xcffib.xproto.CW.BackPixmap
# XCB_PROP_MODE_REPLACE = xcffib.xproto.PropMode.Replace
# XCB_ATOM_PIXMAP = xcffib.xproto.Atom.PIXMAP

# # import pdb; pdb.set_trace()

# monitors = []
# for m in ext_x.QueryScreens().reply().screen_info:
#     print(dir(m))
#     monitors.append((m.x_org, m.y_org, m.width, m.height))

# print(monitors)

# r = setup.roots[0]

# root = r.root
# depth = r.root_depth
# visual = r.root_visual
# width = r.width_in_pixels
# height = r.height_in_pixels

# # just in case it differs
# old_pixmaps = set()
# for i in [_XROOTPMAP_ID, ESETROOT_PMAP_ID]:
#     old_pixmaps.add(conn.core.GetPropertyUnchecked(False, root, i, XCB_ATOM_PIXMAP, 0, 1).reply().value.to_atoms()[0])

# # import pdb; pdb.set_trace()

# max_req_length = conn.get_maximum_request_length() * 4 # counted as ints

# # https://github.com/Elv13/awesome/blob/master/root.c
# picture = conn.generate_id()
# gc = conn.generate_id()

# conn.core.CreateGC(gc, root, 0, None)


# conn.core.CreatePixmap(depth, picture, root, width, height)

# block_width = 2048
# block_height = 2048
# image = Image.new('RGBA', (block_width, block_height), color = 'blue')
# data = image.tobytes('raw', 'BGRA')

# print(len(data))
# # 4194303


# # import pdb; pdb.set_trace()

# conn.core.PutImage(xcffib.xproto.ImageFormat.ZPixmap, picture, gc, block_width, block_height, 2000, 2000, 0, depth, len(data), data)
# conn.core.FreeGC(gc)

# conn.core.ChangeWindowAttributes(root, XCB_CW_BACK_PIXMAP, [picture])
# conn.core.ClearArea(0, root, 0,0,0,0)

# conn.core.ChangeProperty(XCB_PROP_MODE_REPLACE, root, _XROOTPMAP_ID, XCB_ATOM_PIXMAP, 32, 1, [picture])
# conn.core.ChangeProperty(XCB_PROP_MODE_REPLACE, root, ESETROOT_PMAP_ID, XCB_ATOM_PIXMAP, 32, 1, [picture])

# # free old pixmaps
# for p in old_pixmaps:
#     conn.core.KillClient(p)


# # conn.core.FreePixmap(a)

# # don't remove pixmap after disconnecting
# conn.core.SetCloseDownMode(xcffib.xproto.CloseDown.RetainPermanent)
# conn.flush()
# conn.disconnect()

class Monitor(object):
    def __init__(self, x, y, width, height):
        super()
        self.x = x
        self.y = y
        self.width = width
        self.height = height

class Picture(object):
    _req_mode = "RGBA"

    def __init__(self, image, x=0, y=0):
        super()
        self.x = x
        self.y = y

        self.image = image
    
    @classmethod
    def load(cls, path, x=0, y=0):
        return cls(PIL.Image.open(path), x, y)

    def get_image(self, monitor):
        image = self.image if self.image.mode == self._req_mode else self.image.convert(self._req_mode)

        # image = image.resize((monitor.width, monitor.height), PIL.Image.LANCZOS)
        image = PIL.ImageOps.fit(image, (monitor.width, monitor.height), centering=(0.5, 0.5), method= PIL.Image.LANCZOS)

        return image

class PictureWriter(object):

    def __init__(self):
        super()
        self._pictures = {}

    def connect(self, display=None):
        self.conn = xcffib.connect(display=display or os.environ.get("DISPLAY"))
        self.ext_x = self.conn(xinerama.key)

        # don't remove pixmap after disconnecting
        self.conn.core.SetCloseDownMode(xcffib.xproto.CloseDown.RetainPermanent)

        self._atom_xrootmap = self._get_atom_id("_XROOTPMAP_ID")
        self._atom_esetroot = self._get_atom_id("ESETROOT_PMAP_ID")
    
    def get_monitors(self):
        ret = []
        for m in self.ext_x.QueryScreens().reply().screen_info:
            print(dir(m))
            ret.append(Monitor(m.x_org, m.y_org, m.width, m.height))
        return ret
    
    def _get_atom_id(self, name):
        return self.conn.core.InternAtom(False, len(name), name).reply().atom
    
    def _get_root_window(self):
        return self.conn.get_setup().roots[0]
    
    def _get_old_pixmaps(self, window):
        """Returns unique pixmap ids"""
        pixmaps = set()
        for i in [self._atom_xrootmap, self._atom_esetroot]:
            v = self.conn.core.GetPropertyUnchecked(
                False,
                window,
                i,
                xcffib.xproto.Atom.PIXMAP,
                0,
                1
            ).reply().value.to_atoms()
            if v:
                pixmaps.add(v[0])
        return tuple(pixmaps)

    def _copy_images(self, destination, root, depth):
        max_req_length = self.conn.get_maximum_request_length() # counted as int32 - one pixel

        gc = self.conn.generate_id()
        self.conn.core.CreateGC(gc, root, 0, None)

        for monitor, picture in self._pictures.items():
            block_height = monitor.height
            block_width = int(max_req_length / block_height)
            offset = 0
            picture_for_mon = picture.get_image(monitor)
            while offset < monitor.width:
                if block_width + offset > monitor.width:
                    # last iteration, just recalculate block_width
                    block_width = monitor.width - offset
                crop_box = (offset, 0, offset + block_width, monitor.height)
                
                data = picture_for_mon.crop(crop_box).tobytes('raw', 'BGRA')

                self.conn.core.PutImage(
                    xcffib.xproto.ImageFormat.ZPixmap,
                    destination,
                    gc,
                    block_width,
                    block_height,
                    monitor.x + offset,
                    monitor.y,
                    0,
                    depth,
                    len(data),
                    data
                )

                offset += block_width

        self.conn.core.FreeGC(gc)

    def set_picture(self, picture, monitor):
        self._pictures[monitor] = picture

    def write(self):

        r = self._get_root_window()

        root = r.root
        depth = r.root_depth
        # visual = r.root_visual
        width = r.width_in_pixels
        height = r.height_in_pixels

        # just in case it differs
        old_pixmaps = self._get_old_pixmaps(root)
        
        picture = self.conn.generate_id()
        self.conn.core.CreatePixmap(depth, picture, root, width, height)

        self._copy_images(picture, root, depth)

        self.conn.core.ChangeWindowAttributes(root, xcffib.xproto.CW.BackPixmap, [picture])
        self.conn.core.ClearArea(0, root, 0, 0, 0, 0)

        self.conn.core.ChangeProperty(
            xcffib.xproto.PropMode.Replace,
            root,
            self._atom_xrootmap,
            xcffib.xproto.Atom.PIXMAP,
            32,
            1,
            [picture]
        )
        self.conn.core.ChangeProperty(
            xcffib.xproto.PropMode.Replace,
            root,
            self._atom_esetroot,
            xcffib.xproto.Atom.PIXMAP,
            32,
            1,
            [picture]
        )

        # free old pixmaps
        for p in old_pixmaps:
            self.conn.core.KillClient(p)


        # conn.core.FreePixmap(a)
        # self.conn.core.SetCloseDownMode(xcffib.xproto.CloseDown.RetainPermanent)

        self.conn.flush()
    
    def disconnect(self):
        self.conn.disconnect()

def get_images():
    ret = set()
    for root, _dirs, files in os.walk("/home/glorpen/wallpapers/"):
        for file in files:
            ret.add(os.path.join(root, file))
    return ret

import random
import itertools

def asd():
    p = PictureWriter()
    p.connect()
    mons = p.get_monitors()
    images = random.sample(get_images(), len(mons))

    for m, img in itertools.zip_longest(mons, images):
       p.set_picture(Picture.load(img), m)

    p.write()
    p.disconnect()

# asd()
