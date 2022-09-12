from typing import List
from pydantic import BaseModel
from PySide6.QtCore import QBasicTimer
from PySide6.QtWidgets import QTableWidgetItem
from universalis.models import Listing, Listings
from xivapi.models import Item, Recipe

# class RowData(BaseModel):
#     listing: Listing
#     widget_list: List[QTableWidgetItem]


class ListingData(BaseModel):
    item: Item
    listings: Listings
    timer: QBasicTimer

    class Config:
        arbitrary_types_allowed = True
