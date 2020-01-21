from glorpen.desktop_customizer.whereami.hints import Hint

class MonitorHint(Hint):
    output = None
    output_name = None
    width_mm = None
    height_mm = None
    monitor_name = None
    monitor_serial = None

    @classmethod
    def create(cls, output, output_info, edid):
        pi = cls()
        pi.output = output
        pi.output_name = output_info.name.raw.decode()
        pi.monitor_name = edid.name
        pi.monitor_serial = edid.serial
        pi.width_mm = output_info.mm_width
        pi.height_mm = output_info.mm_height

        return pi
    


class ScreenHint(Hint):
    physical = None
    position = None
    size = None
    rotation = None

    @property
    def x(self):
        return self.position[0] if self.position else None
    @property
    def y(self):
        return self.position[1] if self.position else None
    
    @property
    def width(self):
        return self.size[0] if self.size else None
    @property
    def height(self):
        return self.size[1] if self.size else None

    @classmethod
    def create(cls, physical, crtc_info):
        ret = cls()
        ret.physical = physical
        ret.position = [crtc_info.x, crtc_info.y]
        ret.size = [crtc_info.width, crtc_info.height]
        ret.rotation = crtc_info.rotation
        return ret
