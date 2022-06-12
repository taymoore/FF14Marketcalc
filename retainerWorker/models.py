from typing import List
from pydantic import BaseModel
from universalis.models import Listings
from xivapi.models import Item, Recipe


class RowData(BaseModel):
    retainer: str
    item: Item
    listings: Listings


class TableData(BaseModel):
    row_list: List[RowData]
