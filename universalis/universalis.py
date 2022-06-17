import json
from typing import Any, Dict, Optional, Tuple, TypeVar, Union
import logging
import time
from pydantic import BaseModel
import requests
from PySide6.QtCore import QMutex
from cache import Persist, persist_to_file

from universalis.models import Listings

_logger = logging.getLogger(__name__)

GET_CONTENT_RATE = 0.05
get_content_time = time.time() - GET_CONTENT_RATE

universalis_mutex = QMutex()

CACHE_TIMEOUT_S = 3600
CACHE_FILENAME = "listings.json"

cache: Dict[Any, Tuple[Listings, float]]
try:
    cache = {
        param: (
            Listings.parse_raw(value[0]),
            value[1],
        )
        for param, value in json.load(open(f".data/{CACHE_FILENAME}", "r")).items()
    }
except (IOError, ValueError):
    _logger.log(logging.WARN, f"Error loading {CACHE_FILENAME} cache")
    cache = {}


def save_to_disk() -> None:
    try:
        new_cache: Dict[Any, Tuple[str, float]] = {
            param: (
                value[0].json(),
                value[1],
            )
            for param, value in cache.items()
        }
        json.dump(new_cache, open(f".data/{CACHE_FILENAME}", "w"), indent=2)
    except Exception as e:
        print(str(e))


def _get_listings(id: int, world: Union[int, str]) -> Listings:
    url = f"https://universalis.app/api/v2/{world}/{id}"
    global get_content_time
    now_time = time.time()
    if now_time - get_content_time < GET_CONTENT_RATE:
        time.sleep(GET_CONTENT_RATE - now_time + get_content_time)
    get_content_time = time.time()
    content_response = requests.get(url)
    while content_response.status_code != 200:
        time.sleep(0.05)
        _logger.log(logging.WARN, f"Error code {content_response.status_code}")
        content_response = requests.get(url)
    content_response.raise_for_status()
    return Listings.parse_obj(content_response.json())


def get_listings(
    id: int, world: Union[int, str], cache_timeout_s: Optional[float] = None
) -> Listings:
    _cache_timeout_s = (
        cache_timeout_s if cache_timeout_s is not None else CACHE_TIMEOUT_S
    )
    _args = [id, world]

    if str(_args) in cache:
        _logger.log(
            logging.DEBUG,
            f"Age of {CACHE_FILENAME}->{_args} Cache: {time.time() - cache[str(_args)][1]}s",
        )
    if str(_args) not in cache or time.time() - cache[str(_args)][1] > _cache_timeout_s:
        cache[str(_args)] = (_get_listings(id, world), time.time())

    return cache[str(_args)][0]
