from functools import partial, wraps
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    Generator,
)
import logging
import requests
import time
import json, atexit
from pydantic import BaseModel
from pydantic_collections import BaseCollectionModel

_logger = logging.getLogger(__name__)


class Persist:
    func: Callable

    def __init__(
        self,
        func: Callable,
        filename: str,
        cache_timeout_s: float,
        return_type: Union[BaseCollectionModel, BaseModel],
    ) -> None:
        self.timeout_s = cache_timeout_s
        self.func = func
        self.filename = filename
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
            json.dump(new_cache, open(f".data/{self.filename}", "w"))
        except Exception as e:
            print(str(e))

    def __call__(
        self, *args: Any, cache_timeout_s: Optional[float] = None, **kwargs: Any
    ) -> Any:
        _cache_timeout_s = (
            cache_timeout_s if cache_timeout_s is not None else self.timeout_s
        )
        if args is None:
            _args: Union[List[Any], str] = []
        else:
            _args = list(args)
        for kwarg_value in kwargs.values():
            _args.append(kwarg_value)

        if len(_args) == 0:
            if len(self.cache) > 0:
                _logger.log(
                    logging.DEBUG,
                    f"Age of {self.filename} Cache: {time.time() - self.cache['null'][1]}s",
                )
            if (
                len(self.cache) == 0
                or time.time() - self.cache["null"][1] > _cache_timeout_s
            ):
                self.cache["null"] = (self.func(), time.time())
            _args = "null"
        else:
            if str(_args) in self.cache:
                _logger.log(
                    logging.DEBUG,
                    f"Age of {self.filename}->{_args} Cache: {time.time() - self.cache[str(_args)][1]}s",
                )
            if (
                str(_args) not in self.cache
                or time.time() - self.cache[str(_args)][1] > _cache_timeout_s
            ):
                self.cache[str(_args)] = (self.func(*_args), time.time())

        return self.cache[str(_args)][0]


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
            # new_cache: Dict[Any, Tuple[str, float]] = {
            #     param: (
            #         value[0].json()
            #         if isinstance(value[0], BaseModel)
            #         or isinstance(value[0], BaseCollectionModel)
            #         else return_type.parse_obj(value[0]).json(),
            #         value[1],
            #     )
            #     for param, value in cache.items()
            # }
            print("cache")
            json.dump(new_cache, open(f".data/{file_name}", "w"))
            print("dump")
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
