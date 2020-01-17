import logging
import itertools
from glorpen.desktop_customizer.layout import Placement, LayoutManager, Rotation, Layout
from glorpen.desktop_customizer.wallpaper import ImageFinder, PictureWriter, Monitor

class ExampleLayout(Layout):

    mon_right = Placement(
        rotation=Rotation.Rotate_90,
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

        
def set_wallpapers(configured_outputs):
    f = ImageFinder("/home/glorpen/wallpapers/")

    p = PictureWriter()
    p.connect()
    images = f.get_unique_random(len(configured_outputs))

    for co, img in itertools.zip_longest(configured_outputs, images):
        img.load()
        p.set_picture(
            img,
            Monitor(co.placement.position[0], co.placement.position[1], co.width, co.height)
        )

    p.write()
    p.disconnect()

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    sl = ExampleLayout()

    l = LayoutManager()
    l.add_layout(sl)
    l.connect()
    
    configured_outputs = l.apply()
    set_wallpapers(configured_outputs)
