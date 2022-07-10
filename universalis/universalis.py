import json
from pathlib import Path
import pickle
from typing import Any, Dict, List, Optional, Tuple, TypeVar, Union
import logging
import time
import pandas as pd
from pydantic import BaseModel
import requests
from PySide6.QtCore import QMutex, Signal
from cache import Persist, persist_to_file

from universalis.models import Listings
from xivapi.models import Item, Recipe

_logger = logging.getLogger(__name__)

GET_CONTENT_RATE = 0.05
get_content_time = time.time() - GET_CONTENT_RATE

universalis_mutex = QMutex()

CACHE_TIMEOUT_S = 3600 * 4
CACHE_FILENAME = "listings.bin"

cache: Dict[Any, Tuple[Listings, float]]
try:
    if Path(f".data/{CACHE_FILENAME}").exists():
        cache = pickle.load(open(f".data/{CACHE_FILENAME}", "rb"))
    else:
        cache = {}
        _logger.info("Created new listings cache")
    # for cache_tuple in cache.values():
    #     listings = cache_tuple[0]
    #     listings.history = (
    #         pd.read_json(listings.history, convert_axes=False)
    #         if listings.history is not None
    #         else pd.DataFrame(columns=["Price"])
    #     )
    #     listings.listing_history = (
    #         pd.read_json(listings.listing_history, convert_axes=False)
    #         if listings.listing_history is not None
    #         else pd.DataFrame(columns=["Price"])
    #     )
    #     listings.history.index = listings.history.index.astype("float64")
    #     listings.listing_history.index = listings.listing_history.index.astype(
    #         "float64"
    #     )
except (IOError, ValueError):
    _logger.log(logging.WARN, f"Error loading {CACHE_FILENAME} cache")
    cache = {}


def save_to_disk() -> None:
    pickle.dump(cache, open(f".data/{CACHE_FILENAME}", "wb"))


def _get_listings(id: int, world: Union[int, str]) -> Listings:
    url = f"https://universalis.app/api/v2/{world}/{id}?noGst=true"
    global get_content_time
    now_time = time.time()
    if now_time - get_content_time < GET_CONTENT_RATE:
        time.sleep(GET_CONTENT_RATE - now_time + get_content_time)
    for _ in range(10):
        try:
            content_response = requests.get(url)
            get_content_time = time.time()
            content_response.raise_for_status()
        except Exception as e:
            time.sleep(0.05)
            print(str(e))
        else:
            break
    if content_response is not None:
        return Listings.parse_obj(content_response.json())
    else:
        raise RuntimeError("Failed to get Universalis Content")


seller_id = None


def set_seller_id(id: str) -> None:
    global seller_id
    seller_id = id


def seller_id_in_listings(listings: Listings) -> bool:
    global seller_id
    return seller_id is not None and any(
        listing.sellerID == seller_id for listing in listings.listings
    )


def seller_id_in_recipe(recipe: Recipe, world_id: int) -> List[Listings]:
    global seller_id
    listings_list = []
    listings = get_listings(recipe.ItemResult.ID, world_id)
    if seller_id_in_listings(listings):
        listings_list.append(listings)
    for ingredient_index in range(9):
        item: Item = getattr(recipe, f"ItemIngredient{ingredient_index}")
        if item is not None:
            listings = get_listings(item.ID, world_id)
            if seller_id_in_listings(listings):
                listings_list.append(listings)
    return listings_list


def is_listing_expired(
    id: int,
    world: Union[int, str],
    time_s: float,
    cache_timeout_s: Optional[float] = None,
) -> bool:
    _args = [id, world]
    _cache_timeout_s = (
        cache_timeout_s if cache_timeout_s is not None else CACHE_TIMEOUT_S
    )
    return str(_args) not in cache or time_s - cache[str(_args)][1] > _cache_timeout_s


def get_listings(
    id: int,
    world: Union[int, str],
    cache_timeout_s: Optional[float] = None,
) -> Listings:
    _cache_timeout_s = (
        cache_timeout_s if cache_timeout_s is not None else CACHE_TIMEOUT_S
    )
    _args = [id, world]

    universalis_mutex.lock()
    if str(_args) in cache:
        _logger.log(
            logging.DEBUG,
            f"Age of {CACHE_FILENAME}->{_args} Cache: {time.time() - cache[str(_args)][1]}s",
        )
    if str(_args) not in cache or time.time() - cache[str(_args)][1] > _cache_timeout_s:
        listings = _get_listings(id, world)

        # TODO: Rename history to purchase_history

        # Merge history and listing_history
        if str(_args) in cache:
            listings.history = cache[str(_args)][0].history
            listings.listing_history = cache[str(_args)][0].listing_history
        else:
            listings.history = pd.DataFrame(columns=["Price"])
            listings.listing_history = pd.DataFrame(columns=["Price"])
        try:
            for recent_history_listing in listings.recentHistory:
                listings.history.loc[
                    recent_history_listing.timestamp
                ] = recent_history_listing.pricePerUnit
        except Exception as e:
            print(f"Error adding purchase history to listings: {e}")
            print(f"Tried to add {recent_history_listing}")
            print(f"listings history: {listings.history}")
            raise e
        try:
            for listing in listings.listings:
                listings.listing_history.loc[
                    listing.lastReviewTime
                ] = listing.pricePerUnit
        except Exception as e:
            print(f"Error adding current listings: {e}")
            print(f"Tried to add {listing}")
            print(f"to listings: {listings.listing_history}")
            raise e

        # Velocity calculation
        if (
            len(listings.history.index) > 0
            and listings.history.index.max() != listings.history.index.min()
        ):
            listings.regularSaleVelocity = (
                3600 * 24 * 7 * len(listings.history.index)
            ) / (listings.history.index.max() - listings.history.index.min())

        cache[str(_args)] = (listings, time.time())

    data = cache[str(_args)][0]
    universalis_mutex.unlock()
    return data
