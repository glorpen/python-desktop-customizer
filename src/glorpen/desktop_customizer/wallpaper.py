#!/usr/bin/env python3

import xcffib
import xcffib.xproto
import os
import struct
import PIL
import PIL.Image
import PIL.ImageOps
import xattr
import logging
import random
import itertools

class Monitor(object):
    def __init__(self, x, y, width, height, name=None):
        super().__init__()
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.name = name
    def __repr__(self):
        return '<{cls}: {d!r}>'.format(cls=self.__class__.__name__, d=self.__dict__ if self.name is None else self.name)

class Picture(object):
    _req_mode = "RGBA"

    poi = None
    image = None

    # TODO: is_offensive
    # TODO: is_safe

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__qualname__)
    
    def load(self):
        raise NotImplementedError()

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
    
    def get_uri(self):
        raise NotImplementedError()
    
    def __eq__(self, other):
        return self.get_uri() == other.get_uri()
    
    def __repr__(self):
        return "<%s: %r>" % (self.__class__.__qualname__, self.get_uri())
    def __hash__(self):
        return hash(self.get_uri())

class FilePicture(Picture):
    _xattr_poi = "user.glorpen.wallpaper.poi"

    def __init__(self, path):
        super().__init__()
        self.path = path
    
    def get_uri(self):
        return self.path
    
    def load(self):
        self.image = PIL.Image.open(self.path)

        try:
            poi = xattr.getxattr(self.path, self._xattr_poi)
            self.poi = [int(i) for i in poi.split(b"x")]
        except OSError:
            pass

class PictureWriter(object):

    def __init__(self):
        super().__init__()
        self.logger = logging.getLogger(self.__class__.__name__)
        self._pictures = {}

    def connect(self, display=None):
        self.conn = xcffib.connect(display=display or os.environ.get("DISPLAY"))

        # don't remove pixmap after disconnecting
        self.conn.core.SetCloseDownMode(xcffib.xproto.CloseDown.RetainPermanent)

        self._atom_xrootmap = self._get_atom_id("_XROOTPMAP_ID")
        self._atom_esetroot = self._get_atom_id("ESETROOT_PMAP_ID")
    
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

                self.logger.debug("Copying cropped image ({crop[0]},{crop[1]}),({crop[2]},{crop[3]}) from {p!r}".format(crop=crop_box, p=picture))

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

class ImageFinder(object):
    def __init__(self, root_dir):
        super().__init__()

        self.root_dir = root_dir
    
    def get_images(self):
        ret = set()
        for root, _dirs, files in os.walk(self.root_dir):
            for file in files:
                ret.add(FilePicture(os.path.join(root, file)))
        return tuple(ret)

    def get_unique_random(self, count, excludes=[]):
        images = list(filter(lambda x: x not in excludes, self.get_images()))

        images_count = len(images)
        if images_count == 0:
            raise Exception("No unused images found in %r" % self.root_dir)
        # if images_count < count:
        #     return random.choices(images, k=count)
        return random.sample(images, count)
