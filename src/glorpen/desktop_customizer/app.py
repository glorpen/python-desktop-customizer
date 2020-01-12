#!/usr/bin/env python3

import xcffib
import xcffib.xproto
import xcffib.xinerama as xinerama
import os
import struct
import PIL
import PIL.Image
import PIL.ImageOps
import xattr
import logging

class Monitor(object):
    def __init__(self, x, y, width, height):
        super()
        self.x = x
        self.y = y
        self.width = width
        self.height = height

class Picture(object):
    _req_mode = "RGBA"

    _xattr_poi = "user.glorpen.wallpaper.poi"

    def __init__(self, image, path, x=0, y=0, poi=None):
        super()

        self.logger = logging.getLogger(self.__class__.__name__)

        self.x = x
        self.y = y
        self.poi = poi
        self.path = path

        self.image = image
    
    @classmethod
    def get_attr_poi(cls, path):
        try:
            poi = xattr.getxattr(path, cls._xattr_poi)
        except OSError as e:
            return None

        return [int(i) for i in poi.split(b"x")]

    @classmethod
    def load(cls, path, x=0, y=0):
        return cls(PIL.Image.open(path), path, x, y, poi=cls.get_attr_poi(path))

    def get_image(self, monitor):
        image = self.image if self.image.mode == self._req_mode else self.image.convert(self._req_mode)

        # find Point of Interest to later center on
        poi = [0.5 * image.width, 0.5 * image.height]
        if self.poi:
            poi = self.poi
        
        self.logger.debug("POI is at %r on %r", poi, monitor)

        # we should take image dimension that is smallest
        # and make it ratio value
        ratio = min(image.width / monitor.width, image.height / monitor.height)

        # numpy and multiplying arrays?
        cropped_size = [round(ratio * monitor.width), round(ratio * monitor.height)]

        # center cropped box on poi and crop image
        # coords are based on original image
        offset = [0, 0]
        
        for dim in [0, 1]:
            half = cropped_size[dim] / 2
            o = max(poi[dim] - half, 0)
            overflow = max(cropped_size[dim] + o - image.size[dim], 0)
            o -= overflow
            offset[dim] = o

        image = image.crop([offset[0], offset[1], offset[0]+cropped_size[0], offset[1]+cropped_size[1]])
        image = image.resize((monitor.width, monitor.height), resample=PIL.Image.LANCZOS)

        return image
    
    def __repr__(self):
        return "<%s: %r>" % (self.__class__.__qualname__, self.path)

class PictureWriter(object):

    def __init__(self):
        super()
        self.logger = logging.getLogger(self.__class__.__name__)
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
        self.logger.debug("Setting %r on %r", picture, monitor)
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

logging.basicConfig(level=logging.DEBUG)
asd()
