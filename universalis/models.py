from typing import Any, Dict, List, Optional, Tuple, Type, Union
from pydantic import BaseModel
from pydantic_collections import BaseCollectionModel


class Listing(BaseModel):
    lastReviewTime: Optional[int]
    pricePerUnit: int
    quantity: int
    hq: bool
    isCrafted: Optional[bool]
    total: int


# class Listings(BaseCollectionModel[Listing]):
#     class Config:
#         validate_assignment_strict = False


class Listings(BaseModel):
    itemID: int
    worldID: Optional[int]
    lastUploadTime: int
    listings: List[Listing]
    recentHistory: List[Listing]
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
    worldName: Optional[str]
