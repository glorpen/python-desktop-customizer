import logging
import itertools
import platform
import asyncio
import subprocess
from glorpen.desktop_customizer.layout import Placement, LayoutManager, Rotation, Layout
from glorpen.desktop_customizer.wallpaper import ImageFinder, PictureWriter, Monitor, DictCache
from glorpen.desktop_customizer.whereami.detection import DetectionInfo
from glorpen.desktop_customizer.whereami.hints.xrand import ScreenHint, MonitorHint
from glorpen.desktop_customizer.whereami.hints.simple import WifiHint, HostHint
from glorpen.desktop_customizer.automation.dimmer import Dimmer
import asyncio

class WallpaperManager(object):
    def __init__(self, path):
        super().__init__()
        self.finder = ImageFinder(path, cache=DictCache())
        self.cache = {}

    async def set_wallpapers(self, screens, *args):
        new_screens = []

        p = PictureWriter()
        p.connect()

        for s in screens.values():
            output = s.physical.output
            if output in self.cache:
                p.set_picture(
                    self.cache[output],
                    Monitor(s.x, s.y, s.width, s.height, name=s.physical.output_name)
                )
            else:
                new_screens.append(s)

        if new_screens:
            new_images = self.finder.get_unique_random(len(new_screens), self.cache.values())

            for co, img in itertools.zip_longest(new_screens, new_images):
                self.cache[co.physical.output] = img
                p.set_picture(
                    img,
                    Monitor(co.x, co.y, co.width, co.height, name=co.physical.output_name)
                )

        p.write()
        p.disconnect()

from glorpen.desktop_customizer.config import reader as config_reader
import itertools

class ActionCallback(object):
    def __init__(self, condition, action, watch, events, actions):
        super().__init__()
        self.condition = condition
        self.action = action
        self.watch = watch
        self.events = events
        self.actions = actions
    
    async def __call__(self, *args):
        kwargs = dict(i for i in itertools.zip_longest(self.events, args))
        
        if not self.condition(**kwargs):
            print("skipping", kwargs)
            return
        
        if self.watch:
            print(self.watch)
        # TODO: check watch values for changes since last time

        for a in self.action:
            for k,v in a.items():
                if k in self.actions:
                    await self.actions[k].do(**kwargs, **v)
                else:
                    print("Unknown action %r" % k)

class WallpaperAction(object):
    def __init__(self, wm):
        super().__init__()

        self.wm = wm
        
    async def do(self, screen, safe, **kwargs):
        await self.wm.set_wallpapers(screen)

class DynamicLayout(Layout):
    def __init__(self):
        super().__init__()

        self.placements = {}

    def fit(self, hints):
        self.hints = hints
        return True
    
    def get_placement_for_output(self, output):
        if output in self.placements:
            return self.placements[output]

class LayoutAction(object):
    def __init__(self, lm, dl):
        super().__init__()

        self.lm = lm
        self.dl = dl
    
    async def do(self, monitor, monitors, **kwargs):
        placements = {}
        for m in monitor.values():
            for cm in monitors:
                if cm["output"] is not None and cm["output"] != m.output_name:
                    continue
                if cm["name"] is not None and cm["name"] != m.monitor_name:
                    continue
                if cm["serial"] is not None and cm["serial"] != m.monitor_serial:
                    continue
                
                placements[m.output] = Placement(
                    rotation=cm["rotation"],
                    primary=cm["primary"],
                    position=[int(cm["position"]["x"]), int(cm["position"]["y"])]
                )
                break

        self.dl.placements = placements
        await self.lm.apply(monitor)

class CommandAction(object):
    async def do(self, args, **kwargs):
        await asyncio.create_subprocess_exec(*args)

def from_config(cfg):
    wm = WallpaperManager(cfg["wallpaper"]["directory"])
    lm = LayoutManager()
    dl = DynamicLayout()
    
    dinfo = DetectionInfo()
    events = {
        "screen": ScreenHint,
        "wifi": WifiHint,
        "host": HostHint,
        "monitor": MonitorHint
    }

    actions = {
        "wallpaper": WallpaperAction(wm),
        "layout": LayoutAction(lm, dl),
        "command": CommandAction()
    }
    lm.add_layout(dl)

    for action in cfg["actions"]:
        mapped_events = tuple(map(events.get, action["events"]))
        dinfo.add_listener(mapped_events, ActionCallback(action["if"], action["do"], action["watch"], action["events"], actions))
    
    dinfo.start()

    dimmer = Dimmer()

    dimmer.connect()
    lm.connect()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.gather(dinfo.watch(), dimmer.loop()))

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)

    config = config_reader("/mnt/sandbox/workspace/glorpen/desktop-customizer/config.yaml")
    from_config(config)
    # print(config)
