
import json
import pickle
from typing import Any, Dict, Tuple
import logging
import pandas as pd

from universalis.models import Listings

OLD_CACHE_FILENAME = "listings.json"
NEW_CACHE_FILENAME = "listings.bin"

cache: Dict[Any, Tuple[Listings, float]] = {
    param: (
        Listings.parse_raw(value[0]),
        value[1],
    )
    for param, value in json.load(open(f".data/{OLD_CACHE_FILENAME}", "r")).items()
}
for cache_tuple in cache.values():
    listings = cache_tuple[0]
    listings.history = (
        pd.read_json(listings.history, convert_axes=False)
        if listings.history is not None
        else pd.DataFrame(columns=["Price"])
    )
    listings.listing_history = (
        pd.read_json(listings.listing_history, convert_axes=False)
        if listings.listing_history is not None
        else pd.DataFrame(columns=["Price"])
    )
    listings.history.index = listings.history.index.astype("float64")
    listings.listing_history.index = listings.listing_history.index.astype(
        "float64"
    )


# for cache_tuple in cache.values():
#     listings = cache_tuple[0]
#     # listings.history = listings.history.to_json()
#     # listings.listing_history = listings.listing_history.to_json()
try:
    # new_cache: Dict[Any, Tuple[str, float]] = {
    #     param: (
    #         value[0].json(),
    #         value[1],
    #     )
    #     for param, value in cache.items()
    # }
    # json.dump(new_cache, open(f".data/{CACHE_FILENAME}", "w"), indent=2)
    with open(f".data/{NEW_CACHE_FILENAME}", "wb") as f:
        pickle.dump(cache, f)
except Exception as e:
    print(str(e))

