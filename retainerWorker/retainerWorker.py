import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from copy import copy
import pickle
from PySide6.QtCore import (
    Slot,
    Signal,
    QSize,
    QObject,
    QMutex,
    QSemaphore,
    QThread,
    QBasicTimer,
    QTimerEvent,
)
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTableWidgetItem
from ff14marketcalc import get_profit
from retainerWorker.models import ListingData
from universalis.universalis import get_listings

from xivapi.models import ClassJob, Recipe, RecipeCollection
from universalis.models import Listing, Listings
from xivapi.xivapi import get_classjob_doh_list, get_item, get_recipes

_logger = logging.getLogger(__name__)

ROW_REFRESH_PERIOD_MS = 60000  # 1 min


class RetainerWorker(QObject):
    listing_data_updated = Signal(dict)

    def __init__(self, seller_id: str, world_id: int) -> None:
        super().__init__()
        self.seller_id = seller_id
        self.world_id = world_id
        self.table_data: Dict[int, ListingData] = {}  # timerId: ListingData
        self.running = True
        self.file_path = Path(".data/retainer_worker_cache.bin")
        _logger.setLevel(logging.DEBUG)

    def load_cache(self) -> None:
        try:
            if self.file_path.exists():
                with self.file_path.open("rb") as f:
                    listings_list = pickle.load(f)
                    for listings in listings_list:
                        self.on_retainer_listings_changed(listings)
        except Exception as e:
            _logger.exception(e)

    def save_cache(self) -> None:
        with self.file_path.open("wb") as f:
            pickle.dump(
                [listing_data.listings for listing_data in self.table_data.values()], f
            )

    def build_listing_data(self, listings: Listings) -> ListingData:
        listing_data = ListingData(
            item=get_item(listings.itemID),
            listings=listings,
            timer=QBasicTimer(),
        )
        listing_data.timer.start(ROW_REFRESH_PERIOD_MS, self)
        return listing_data

    def update_listing_data(self, listing_data: ListingData) -> ListingData:
        listing_data.listings = get_listings(
            listing_data.item.ID, self.world_id, cache_timeout_s=0
        )

    def timerEvent(self, event: QTimerEvent) -> None:
        if (listing_data := self.table_data.get(event.timerId())) is not None:
            if any(
                listing.sellerID == self.seller_id
                for listing in listing_data.listings.listings
            ):
                self.update_listing_data(listing_data)
                self.listing_data_updated.emit(listing_data)
            else:
                listing_data.timer.stop()
                del self.table_data[event.timerId()]
        else:
            super().timerEvent(event)

    @Slot(Listings)
    def on_retainer_listings_changed(self, listings: Listings) -> None:
        if not any(
            row_data.listings.itemID == listings.itemID
            for row_data in self.table_data.values()
        ):
            listing_data = self.build_listing_data(listings)
            self.listing_data_updated.emit(listing_data)
            self.table_data[listing_data.timer.timerId()] = listing_data
