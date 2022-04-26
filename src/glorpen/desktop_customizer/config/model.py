import collections.abc
import pathlib
import types
import typing
from dataclasses import dataclass, field, fields, is_dataclass, MISSING, Field

from jinja2.environment import TemplateExpression, Template, Environment


class UserPath(pathlib.Path):
    pass


class ExistingUserPath(pathlib.Path):
    pass


@dataclass
class FileConfig:
    src: typing.Optional[ExistingUserPath]
    template: typing.Optional[Template]
    target: UserPath
    reload_command: typing.Optional[str]

    def validate(self):
        if (self.src and self.template) or (not self.src and not self.template):
            raise ValueError("One of: src, template has to be provided")


@dataclass(kw_only=True)
class WallpaperConfig:
    dir: typing.Optional[ExistingUserPath]
    offensive: typing.Optional[bool]


@dataclass(kw_only=True)
class CommandConfig:
    run: str
    watch: typing.Sequence[TemplateExpression]


@dataclass(kw_only=True)
class MonitorConfig:
    x: int
    y: int
    selector: TemplateExpression
    rotation: int = field(default=0)


@dataclass(kw_only=True)
class DynamicMonitorConfig:
    placement: typing.Literal["left", "right"]


@dataclass(kw_only=True)
class NestedConfig:
    monitors: typing.Dict[str, typing.Union[MonitorConfig, DynamicMonitorConfig]] = field(
        default_factory=dict, kw_only=True)
    files: typing.Dict[str, FileConfig] = field(default_factory=dict, kw_only=True)
    commands: typing.Dict[str, CommandConfig] = field(default_factory=dict, kw_only=True)
    wallpaper: WallpaperConfig = field(default_factory=dict, kw_only=True)


@dataclass(kw_only=True)
class PlaceConfig(NestedConfig):
    selector: TemplateExpression


@dataclass(kw_only=True)
class MainConfig(NestedConfig):
    places: typing.Dict[str, PlaceConfig]


class Loader:
    """
    Custom simple typehint/dataclass filler & validator.

    Pydantic does not have nice third party types registration and does not support validation context,
    Marshmallow has own classes and environment.
    """

    def __init__(self, config_path: pathlib.Path, env: Environment):
        self._config_path = config_path
        self._env = env

    def _try_each_hint(self, data, types, path: str):
        e = []
        for maybe_type in types:
            try:
                return self._get_any(data, maybe_type, MISSING, path)
            except Exception as ee:
                e.append(f"    - {maybe_type.__name__}: {ee}")

        raise ValueError(f"""{path}: Could not convert to any of:\n""" + "\n".join(e))

    def _get_custom_type(self, data, type_):
        if type_ is pathlib.Path:
            return pathlib.Path(data)

        if type_ is bool:
            return bool(data)
        if type_ is str:
            return str(data)
        if type_ is int:
            return int(data)
        if type_ is Template:
            return self._env.from_string(data)
        if type_ is TemplateExpression:
            return self._env.compile_expression(data)
        if type_ is ExistingUserPath:
            return (self._config_path.parent / pathlib.Path(data).expanduser()).resolve(strict=True)
        if type_ is UserPath:
            return (self._config_path.parent / pathlib.Path(data).expanduser()).resolve()

    def _get_typehint(self, data, type_, default, path):
        origin = typing.get_origin(type_)

        if origin is typing.Union:
            return self._try_each_hint(data, typing.get_args(type_), path)

        if data is not None:
            if origin is dict:
                args = typing.get_args(type_)
                ret = {}
                for k, v in data.items():
                    ret[self._get_any(k, args[0], MISSING, f"{path}.{k}:key")] = self._get_any(v, args[1], MISSING,
                        f"{path}.{k}")
                return ret
            if origin is typing.Literal:
                args = typing.get_args(type_)
                if data in args:
                    return data
                else:
                    raise ValueError(f"{path}: {data} is not one of {args}")

            if origin and issubclass(origin, collections.abc.Sequence):
                args = typing.get_args(type_)
                ret = []
                for index, i in enumerate(data):
                    ret.append(self._get_any(i, args[0], MISSING, f"{path}.{index}"))
                return tuple(ret)

            try:
                ret = self._get_custom_type(data, type_)
            except Exception as e:
                raise ValueError(f"{path}: {e}")
            if ret is not None:
                return ret

            raise NotImplementedError(f"{path}: not supported typehint {type_}")

        else:
            if default is not MISSING:
                return default

            if type_ is types.NoneType:
                return None

            raise ValueError(f"{path} is required")

    def _get_any(self, data, cls_or_type, default, path: str):
        if is_dataclass(cls_or_type):
            if data is None and default is not MISSING:
                return default
            return self._get_model(data, cls_or_type, path)
        else:
            return self._get_typehint(data, cls_or_type, default, path)

    @classmethod
    def _get_default(cls, f: Field):
        if f.default is not MISSING:
            return f.default
        if f.default_factory is not MISSING:
            return f.default_factory()
        return MISSING

    def _get_model(self, data, cls, path: str):
        kw = {}
        for f in fields(cls):
            kw[f.name] = self._get_any(data.get(f.name, None), f.type, self._get_default(f), f"{path}.{f.name}")
        ret = cls(**kw)
        if hasattr(ret, "validate"):
            try:
                ret.validate()
            except ValueError as e:
                raise ValueError(f"{path}: {e}")
        return ret

    def get_config(self, data: dict) -> MainConfig:
        try:
            return self._get_model(data, MainConfig, "")
        except ValueError as e:
            raise ValueError(e) from None
