from typing import Any, Dict, List, Optional, Tuple, Type, Union
from pydantic import BaseModel
from pydantic_collections import BaseCollectionModel


class Listing(BaseModel):
    lastReviewTime: int
    pricePerUnit: int
    quantity: int
    hq: bool
    isCrafted: bool
    total: int


# class Listings(BaseCollectionModel[Listing]):
#     class Config:
#         validate_assignment_strict = False


class Listings(BaseModel):
    itemID: int
    worldID: int
    lastUploadTime: int
    listings: List[Listing]
    currentAveragePrice: float
    currentAveragePriceNQ: float
    currentAveragePriceHQ: float
    regularSaleVelocity: float
    nqSaleVelocity: float
    hqSaleVelocity: float
    averagePrice: float
    averagePriceNQ: float
    averagePriceHQ: float
    minPrice: float
    minPriceNQ: float
    minPriceHQ: float
    maxPrice: float
    maxPriceNQ: float
    maxPriceHQ: float
    worldName: str
