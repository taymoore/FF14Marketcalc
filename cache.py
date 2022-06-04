from functools import cache, partial
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
        new_cache: Dict[Any, Tuple[str, float]] = {
            param: (
                value[0].json()
                if isinstance(value[0], BaseModel)
                else return_type.parse_obj(value[0]).json(),
                value[1],
            )
            for param, value in cache.items()
        }
        json.dump(new_cache, open(f".data/{file_name}", "w"))

    atexit.register(partial(save_to_disk, cache, file_name, return_type))

    def decorator(func):
        def new_func(*args, **kwargs):
            if args is None:
                args = []
            else:
                args = list(args)
            if kwargs is not None:
                for kwarg_value in kwargs.values():
                    args.append(kwarg_value)

            if len(args) == 0:
                if len(cache) > 0:
                    _logger.log(
                        logging.DEBUG,
                        f"Age of {file_name} Cache: {time.time() - cache['null'][1]}s",
                    )
                if len(cache) == 0 or time.time() - cache["null"][1] > timeout_s:
                    cache["null"] = (func(), time.time())
                args = "null"
            else:
                if str(args) in cache:
                    _logger.log(
                        logging.DEBUG,
                        f"Age of {file_name}->{args} Cache: {time.time() - cache[str(args)][1]}s",
                    )
                if (
                    str(args) not in cache
                    or time.time() - cache[str(args)][1] > timeout_s
                ):
                    cache[str(args)] = (func(*args), time.time())

            return cache[str(args)][0]

        return new_func

    return decorator
