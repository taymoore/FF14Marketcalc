import sys
import abc
from functools import partial, wraps
from pathlib import Path
import pickle
from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    MutableMapping,
    Optional,
    Tuple,
    TypeVar,
    Union,
)
import logging
import time
import json, atexit
from pydantic import BaseModel
from pydantic_collections import BaseCollectionModel
from PySide6.QtCore import QMutex

_logger = logging.getLogger(__name__)


class Persist:
    func: Callable

    def __init__(
        self,
        func: Callable,
        filename: str,
        cache_timeout_s: Optional[float],
        return_type: Union[BaseCollectionModel, BaseModel],
        mutex: bool = True,
    ) -> None:
        self.timeout_s = cache_timeout_s
        self.func = func  # type: ignore
        self.filename = filename
        self.return_type = return_type
        self.mutex = QMutex() if mutex else None
        try:
            self.cache: Dict[Any, Tuple[BaseModel, float]] = {
                param: (
                    return_type.parse_raw(value[0]),
                    value[1],
                )
                for param, value in json.load(
                    open(f".data/{self.filename}", "r")
                ).items()
            }
        except (IOError, ValueError):
            _logger.log(logging.WARN, f"Error loading {self.filename} cache")
            self.cache = {}

    def save_to_disk(self) -> None:
        try:
            new_cache: Dict[Any, Tuple[str, float]] = {
                param: (
                    value[0].json()
                    if isinstance(value[0], BaseModel)
                    or isinstance(value[0], BaseCollectionModel)
                    else self.return_type.parse_obj(value[0]).json(),
                    value[1],
                )
                for param, value in self.cache.items()
            }
            json.dump(new_cache, open(f".data/{self.filename}", "w"), indent=2)
        except Exception as e:
            print(str(e))

    def __call__(self, *args: Any, cache_timeout_s: float = ..., **kwargs: Any) -> Any:
        _cache_timeout_s = (
            cache_timeout_s if cache_timeout_s is not ... else self.timeout_s
        )
        if args is None:
            _args: Union[List[Any], str] = []
        else:
            _args = list(args)
        for kwarg_value in kwargs.values():
            _args.append(kwarg_value)

        if self.mutex is not None:
            self.mutex.lock()
        if len(_args) == 0:
            if len(self.cache) > 0:
                _logger.log(
                    logging.DEBUG,
                    f"Age of {self.filename} Cache: {time.time() - self.cache['null'][1]}s",
                )
            if len(self.cache) == 0 or (
                _cache_timeout_s is not None
                and time.time() - self.cache["null"][1] > _cache_timeout_s
            ):
                self.cache["null"] = (self.func(), time.time())
            _args = "null"
        else:
            if str(_args) in self.cache:
                _logger.log(
                    logging.DEBUG,
                    f"Age of {self.filename}->{_args} Cache: {time.time() - self.cache[str(_args)][1]}s",
                )
            if str(_args) not in self.cache or (
                _cache_timeout_s is not None
                and time.time() - self.cache[str(_args)][1] > _cache_timeout_s
            ):
                self.cache[str(_args)] = (self.func(*_args), time.time())

        data = self.cache[str(_args)][0]
        if self.mutex is not None:
            self.mutex.unlock()
        return data


T = TypeVar("T")


def load_cache(filename: str, default: T) -> T:
    try:
        return pickle.load(open(f".data/{filename}", "rb"))
    except (IOError, ValueError):
        return default


def save_cache(filename: str, data: T) -> None:
    with open(f".data/{filename}", "wb") as f:
        pickle.dump(data, f)


KT = TypeVar("KT")
VT = TypeVar("VT")


# https://stackoverflow.com/a/64323140/7552308
class PersistMapping(MutableMapping[KT, VT]):
    # Cannot get type argument at runtime https://stackoverflow.com/questions/57706180/generict-base-class-how-to-get-type-of-t-from-within-instance
    def __init__(
        self,
        filename: str,
        default: Optional[Dict[KT, VT]] = None,
        **kwargs,
    ) -> None:
        self.data = default if default is not None else {}
        if kwargs:
            self.update(kwargs)
        self.file_path = Path(f".data/{filename}")
        if self.file_path.exists():
            try:
                with self.file_path.open("rb") as f:
                    self.data.update(pickle.load(f))
            except (IOError, ValueError, EOFError, AttributeError) as e:
                _logger.exception(e)
                _logger.error(f"Corrupted {filename} cache. Deleting...")
                input("Press Enter to continue...")
                self.file_path.unlink()
        else:
            _logger.info(f"Created new {self.file_path} cache")

    def __contains__(self, key: KT) -> bool:
        return key in self.data

    def __delitem__(self, key: KT) -> None:
        del self.data[key]

    def __getitem__(self, key: KT) -> VT:
        return self.data[key]

    def __len__(self) -> int:
        return len(self.data)

    def __iter__(self) -> Iterator[KT]:
        return iter(self.data)

    def __setitem__(self, key: KT, value: VT) -> None:
        self.data[key] = value

    def update(self, other=(), /, **kwds) -> None:
        """Updates the dictionary from an iterable or mapping object."""
        if isinstance(other, abc.Mapping):
            for key in other:
                self.data[key] = other[key]
        elif hasattr(other, "keys"):
            for key in other.keys():
                self.data[key] = other[key]
        else:
            for key, value in other:
                self.data[key] = value
        for key, value in kwds.items():
            self.data[key] = value

    def save_to_disk(self) -> None:
        with self.file_path.open("wb") as f:
            pickle.dump(self.data, f)


# class PersistTimeoutMapping(MutableMapping[KT, VT]):
#     def __init__(
#         self,
#         value_type: VT,
#         filename: str,
#         timeout_s: float,
#         default: Dict[KT, VT] = dict(),
#     ) -> None:
#         self.filename = filename
#         self.timeout_s = timeout_s
#         self.data: Dict[KT, List[VT, float]] = {
#             key: [value, time.time()] for key, value in default.items()
#         }
#         if Path(f".data/{self.filename}").exists():
#             try:
#                 self.data.update(
#                     {
#                         param: [value_type.parse_obj(value[0]), value[1]]
#                         for param, value in json.load(
#                             open(f".data/{self.filename}", "r")
#                         ).items()
#                     }
#                 )
#             except (IOError, ValueError):
#                 _logger.log(logging.WARN, f"Error loading {self.filename} cache")
#         else:
#             _logger.info(f"Created new {self.filename} cache")

#     def __contains__(self, key: KT) -> bool:
#         return key in self.data

#     def __delitem__(self, key: KT) -> None:
#         del self.data[key]

#     def get(self, key: KT, timeout_s: float = ..., default: Optional[VT] = ...) -> VT:
#         if timeout_s is ...:
#             timeout_s = self.timeout_s
#         if key in self.data:
#             if time.time() - self.data[key][1] > timeout_s:
#                 del self.data[key]
#             else:
#                 return self.data[key][0]

#     def __getitem__(self, key: KT) -> VT:
#         if key in self.data:
#             return self.data[key][0]
#         raise KeyError(key)

#     def __len__(self) -> int:
#         return len(self.data)

#     def __setitem__(self, key: KT, value: VT) -> None:
#         self.data[key] = [value, time.time()]

#     def update(self, other=()) -> None:
#         if isinstance(other, abc.Mapping):
#             for key in other:
#                 self.data[key] = [other[key], time.time()]
#         elif hasattr(other, "keys"):
#             for key in other.keys():
#                 self.data[key] = [other[key], time.time()]
#         else:
#             for key, value in other:
#                 self.data[key] = [value, time.time()]

#     def save_to_disk(self) -> None:
#         data: Dict[KT, List[dict, float]] = {
#             key: [value[0].dict(), value[1]] for key, value in self.data.items()
#         }
#         json.dump(data, open(f".data/{self.filename}", "w"), indent=2)


def persist_to_file(file_name: str, timeout_s: float, return_type: BaseCollectionModel):

    try:
        cache: Dict[Any, Tuple[BaseModel, float]] = {
            param: (
                return_type.parse_raw(value[0]),
                value[1],
            )
            for param, value in json.load(open(f".data/{file_name}", "r")).items()
        }
    except (IOError, ValueError):
        _logger.log(logging.WARN, f"Error loading {file_name} cache")
        cache = {}

    def save_to_disk(
        cache: Dict[Any, Tuple[Any, float]], file_name: str, return_type: BaseModel
    ):
        print(file_name)
        try:
            new_cache: Dict[Any, Tuple[str, float]] = {}
            for param, value in cache.items():
                print(f"saving {str(param)}")
                print(f"saving {str(value)}")
                value_str = (
                    value[0].json()
                    if isinstance(value[0], BaseModel)
                    else return_type.parse_obj(value[0]).json()
                )
                new_cache[param] = (value_str, value[1])
            json.dump(new_cache, open(f".data/{file_name}", "w"), indent=2)
        except Exception as e:
            print(str(e))

    atexit.register(partial(save_to_disk, cache, file_name, return_type))

    def decorator(func):
        @wraps(func)
        def new_func(*args, cache_timeout_s: Optional[float] = None, **kwargs):
            _timeout_s = cache_timeout_s if cache_timeout_s is not None else timeout_s
            if args is None:
                _args: Union[List[Any], str] = []
            else:
                _args = list(args)
            if kwargs is not None:
                for kwarg_value in kwargs.values():
                    _args.append(kwarg_value)

            if len(_args) == 0:
                if len(cache) > 0:
                    _logger.log(
                        logging.DEBUG,
                        f"Age of {file_name} Cache: {time.time() - cache['null'][1]}s",
                    )
                if len(cache) == 0 or time.time() - cache["null"][1] > _timeout_s:
                    cache["null"] = (func(), time.time())
                _args = "null"
            else:
                if str(_args) in cache:
                    _logger.log(
                        logging.DEBUG,
                        f"Age of {file_name}->{_args} Cache: {time.time() - cache[str(_args)][1]}s",
                    )
                if (
                    str(_args) not in cache
                    or time.time() - cache[str(_args)][1] > _timeout_s
                ):
                    cache[str(_args)] = (func(*_args), time.time())

            return cache[str(_args)][0]

        return new_func

    return decorator


def get_size(obj, seen=None):
    """Recursively finds size of objects"""
    size = sys.getsizeof(obj)
    if seen is None:
        seen = set()
    obj_id = id(obj)
    if obj_id in seen:
        return 0
    # Important mark as seen *before* entering recursion to gracefully handle
    # self-referential objects
    seen.add(obj_id)
    if isinstance(obj, dict):
        size += sum([get_size(v, seen) for v in obj.values()])
        size += sum([get_size(k, seen) for k in obj.keys()])
    elif hasattr(obj, "__dict__"):
        size += get_size(obj.__dict__, seen)
    elif hasattr(obj, "__iter__") and not isinstance(obj, (str, bytes, bytearray)):
        size += sum([get_size(i, seen) for i in obj])
    return size
