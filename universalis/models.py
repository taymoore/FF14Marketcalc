from typing import Any, Dict, List, Optional, Tuple, Type, Union
from pydantic import BaseModel
from pydantic_collections import BaseCollectionModel
import pandas as pd


class Listing(BaseModel):
    lastReviewTime: Optional[int]
    pricePerUnit: int
    quantity: int
    hq: bool
    isCrafted: Optional[bool]
    retainerName: Optional[str]
    sellerID: Optional[str]
    total: int
    timestamp: Optional[int]


# class History(BaseModel):
#     pass


class Listings(BaseModel):
    itemID: int
    worldID: Optional[int]
    lastUploadTime: int
    listings: List[Listing]
    recentHistory: List[Listing]
    history: Optional[Union[pd.DataFrame, str]] = None
    listing_history: Optional[Union[pd.DataFrame, str]] = None
    currentAveragePrice: float
    currentAveragePriceNQ: float
    currentAveragePriceHQ: float
    regularSaleVelocity: float
    nqSaleVelocity: float
    hqSaleVelocity: float
    averagePrice: float
    averagePriceNQ: float
    averagePriceHQ: float
    minPrice: int
    minPriceNQ: int
    minPriceHQ: int
    maxPrice: int
    maxPriceNQ: int
    maxPriceHQ: int

    class Config:
        arbitrary_types_allowed = True
