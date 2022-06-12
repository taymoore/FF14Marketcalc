from typing import Dict, List, Optional, Tuple
from copy import copy
from PySide6.QtCore import Slot, Signal, QSize, QObject, QMutex, QSemaphore, QThread
from ff14marketcalc import get_profit
from universalis.universalis import get_listings

from xivapi.models import ClassJob, Recipe, RecipeCollection
from universalis.models import Listing, Listings
from xivapi.xivapi import get_classjob_doh_list, get_recipes


class RetainerWorker(QObject):
    def __init__(
        self,
    ) -> None:
        super().__init__()
        self.retainer_listings_list: List[Listings] = []
        self.running = True

    def run(self) -> None:
        while self.running:
            pass

    def stop(self) -> None:
        self.running = False

    # @Signal(Listings)
    # def on_retainer_listing_updated(self, listings: Listings) -> None:
    #     if listings not in self.retainer_listings_list:
    #         self.retainer_listings_list.append(listings)
