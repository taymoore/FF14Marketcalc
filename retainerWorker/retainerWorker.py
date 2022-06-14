from typing import Dict, List, Optional, Tuple
from copy import copy
from PySide6.QtCore import Slot, Signal, QSize, QObject, QMutex, QSemaphore, QThread
from ff14marketcalc import get_profit
from retainerWorker.models import RowData
from universalis.universalis import get_listings

from xivapi.models import ClassJob, Recipe, RecipeCollection
from universalis.models import Listing, Listings
from xivapi.xivapi import get_classjob_doh_list, get_item, get_recipes


class RetainerWorker(QObject):
    table_data_changed = Signal(list)

    def __init__(self, seller_id: str) -> None:
        super().__init__()
        self.seller_id = seller_id
        self.table_data: List[RowData] = []
        self.running = True

    # def refresh_listings(self) -> None:
    #     for listings in self.retainer_listings_list:

    def run(self) -> None:
        while self.running:
            QThread.sleep(1)

    def stop(self) -> None:
        self.running = False

    def build_row_data(self, listings: Listings) -> List[RowData]:
        row_data: List[RowData] = []
        for listing in listings.listings:
            if listing.sellerID == self.seller_id:
                row_data.append(
                    RowData(
                        retainer=listing.retainerName,
                        item=get_item(listings.itemID),
                        listings=listings,
                    )
                )
        return row_data

    # @Slot(Listings)
    # def on_retainer_listings_changed(self, listings: Listings) -> None:
    @Slot()
    def on_retainer_listings_changed(self) -> None:
        print("received")
        # if not any(row_data.listings == listings for row_data in self.table_data):
        #     row_data = self.build_row_data(listings)
        #     self.table_data.extend(row_data)
        #     print("emit!")
        #     self.table_data_changed.emit(self.table_data)
        # # if listings not in self.retainer_listings_list:
        # #     self.retainer_listings_list.append(listings)
