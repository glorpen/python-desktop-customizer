import logging
import itertools
import platform
import functools
from glorpen.desktop_customizer.layout import Placement, LayoutManager, Rotation, Layout
from glorpen.desktop_customizer.wallpaper import ImageFinder, PictureWriter, Monitor, DictCache
from glorpen.desktop_customizer.whereami.detection import DetectionInfo
from glorpen.desktop_customizer.whereami.hints.xrand import ScreenHint, MonitorHint
from glorpen.desktop_customizer.whereami.hints.simple import WifiHint
import asyncio

import jinja2
import glorpen.config
import glorpen.config.fields.simple as fs
import glorpen.config.fields.base as fb

env = jinja2.Environment()

class ExpressionField(fb.Field):
    def __init__(self, env):
        super().__init__()
        self.env = env
    
    def normalize(self, raw_value):
        if raw_value is None:
            return fb.SingleValue(self._true, self)
        return fb.SingleValue(self.env.compile_expression(raw_value), self)
    
    def create_packed_value(self, normalized_value):
        return normalized_value.value
    
    def is_value_supported(self, raw_value):
        return raw_value is None or isinstance(raw_value, (str,))

    @classmethod
    def _true(cls, *args, **kwargs):
        return True
    
    # def parse(self, value):
    #     if value is None:
    #         return self._true
    #     return self.env.compile_expression(value)
    # def is_value_supported(self, value):
    #     return value is None or isinstance(value, (str,))
    # def get(self, raw_value):
    #     return self.parse(raw_value)

class JinjaField(fb.Field):
    def __init__(self, env):
        super().__init__()
        self.env = env
    def is_value_supported(self, raw_value):
        return isinstance(raw_value, (str,))
    
    def normalize(self, raw_value):
        tpl = self.env.from_string(raw_value)
        def render(kwargs):
            return fb.SingleValue(tpl.render(**kwargs), self)
        return fb.SingleValue(render, self)
    
    def create_packed_value(self, normalized_value):
        return normalized_value.value


_schema_do = [
    fs.Dict({
        "layout": fs.Dict({
            "monitors": fs.List(fs.Dict({
                "name": fb.Optional(fs.String()),
                "serial": fb.Optional(fs.String()),
                "primary": fb.Optional(fs.Bool(), default=False),
                "position": fs.Dict({
                    "x": fb.Optional(fs.Number()),
                    "y": fb.Optional(fs.Number())
                }),
                "rotation": fb.Optional(fs.Choice({
                    0: Rotation.Rotate_0,
                    90: Rotation.Rotate_90,
                    180: Rotation.Rotate_180,
                    270: Rotation.Rotate_270,
                }), default=Rotation.Rotate_0)
            })),
            "unknown_monitors": fs.Any()
        })
    }, check_keys=True),
    fs.Dict({
        "wallpaper": fs.Dict({
            "safe": fb.Optional(fs.Bool())
        })
    }, check_keys=True),
    fs.Dict({
        "template": fs.Dict({
            "src": fs.PathObj(),
            "target": fs.PathObj(),
            "replacements": fs.Dict(keys=fs.String(), values=JinjaField(env))
        })
    }, check_keys=True),
    fs.Dict({
        "command": fs.Dict({
            "args": fs.List(fs.String())
        })
    }, check_keys=True),
]

_schema = fs.Dict({
    "actions": fs.List(fs.Dict({
        "events": fs.List(fs.Choice(
            ["host", "screen", "monitor", "wifi"]
        ).help(description="Event name")).help(description="Event name to trigger on"),
        "if": ExpressionField(env).help(description="Expression to evaluate", value="1 + 1 == 2"),
        "do": fs.List(fs.Variant(_schema_do)), #, try_resolving=True
        "watch": fb.Optional(fs.List(ExpressionField(env)), default=[])
    })).help(description="Trigger actions"),
    "wallpaper": fs.Dict({
        "directory": fs.PathObj().help(description="Path where files will be searched for", value="/some/path"),
        "cache": fb.Optional(fs.String(), default="memory").help(description="How to cache resized wallpapers"),
        # "safe": fs.Any()
    }).help(description="Configure wallpapers source")
})

from glorpen.config import Config, Translator
from glorpen.config.translators.yaml import YamlReader, YamlRenderer

def reader(path):
    loader = YamlReader(path)
    cfg = Config(_schema)

    t = Translator(cfg)
    return t.read(loader)
    # renderer = YamlRenderer()
    # print(t.generate_example(renderer))
