from typing import Dict, List, Optional, Tuple
from copy import copy
from PySide6.QtCore import Slot, Signal, QSize, QObject, QMutex, QSemaphore, QThread
from ff14marketcalc import get_profit
from universalis.universalis import get_listings, universalis_mutex

from xivapi.models import ClassJob, Recipe, RecipeCollection
from universalis.models import Listing, Listings
from xivapi.xivapi import get_classjob_doh_list, get_recipes, xivapi_mutex


class Worker(QObject):
    status_bar_update_signal = Signal(str)
    table_refresh_signal = Signal()
    retainer_listings_changed = Signal(Listings)
    refresh_recipe_request_sem = QSemaphore()

    def __init__(
        self, world: int, seller_id: str, classjob_level_max_dict: Dict[int, int] = {}
    ) -> None:
        super().__init__()
        self.world = world
        self.seller_id = seller_id
        self.classjob_level_max_dict: Dict[int, int] = classjob_level_max_dict
        self.classjob_level_current_dict: Dict[int, int] = {}
        self.process_todo_recipe_list: RecipeCollection = RecipeCollection()
        self._processed_recipe_list: RecipeCollection = RecipeCollection()
        self._processed_recipe_list_mutex = QMutex()
        self._table_row_data: List[Tuple[str, str, float, float, Recipe]] = []
        self._table_row_data_mutex = QMutex()
        # self._retainer_listings_list: List[Listings] = []
        # self._retainer_listings_list_mutex = QMutex()

        self.running = True

    @property
    def processed_recipe_list(self):
        self._processed_recipe_list_mutex.lock()
        r = copy(self._processed_recipe_list)
        self._processed_recipe_list_mutex.unlock()
        return r

    @property
    def table_row_data(self):
        self._table_row_data_mutex.lock()
        r = copy(self._table_row_data)
        self._table_row_data_mutex.unlock()
        return r

    def refresh_listings(self, recipe_list: List[Recipe]) -> None:
        for recipe_index, recipe in enumerate(recipe_list):
            self.print_status(
                f"Refreshing marketboard data {recipe_index+1}/{len(recipe_list)} ({recipe.ItemResult.Name})..."
            )
            universalis_mutex.lock()
            listings: Listings = get_listings(recipe.ItemResult.ID, self.world)
            universalis_mutex.unlock()
            if any(listing.sellerID == self.seller_id for listing in listings.listings):
                self.retainer_listings_changed.emit(listings)
            if not self.running:
                break

    def service_requests(self):
        if self.refresh_recipe_request_sem.tryAcquire():
            self.refresh_listings(self.processed_recipe_list)
            self.update_table(self.processed_recipe_list)

    def update_table(self, recipe_list: List[Recipe]) -> None:
        self.print_status("Updating table...")
        self._table_row_data_mutex.lock()
        self._table_row_data.clear()
        for recipe in recipe_list:
            self._table_row_data.append(
                (
                    recipe.ClassJob.Abbreviation,
                    recipe.ItemResult.Name,
                    get_profit(recipe, self.world),
                    get_listings(recipe.ItemResult.ID, self.world).regularSaleVelocity,
                    recipe,
                )
            )
        self._table_row_data.sort(key=lambda row: row[2] * row[3], reverse=True)
        self._table_row_data_mutex.unlock()
        self.table_refresh_signal.emit()

    def run(self):
        self.print_status("Getting DOH Classjob list")
        classjob_list = get_classjob_doh_list()

        downloading_recipes = True
        while downloading_recipes:
            downloading_recipes = False
            for classjob_id in self.classjob_level_max_dict.keys():
                if (
                    classjob_level := self.classjob_level_current_dict.setdefault(
                        classjob_id, self.classjob_level_max_dict[classjob_id]
                    )
                ) > 0:
                    classjob: ClassJob = list(
                        filter(
                            lambda classjob: classjob.ID == classjob_id, classjob_list
                        )
                    )[0]
                    self.print_status(
                        f"Getting recipes for class {classjob.Abbreviation} level {classjob_level}..."
                    )
                    xivapi_mutex.lock()
                    self.process_todo_recipe_list.extend(
                        get_recipes(
                            classjob_id=classjob_id, classjob_level=classjob_level
                        )
                    )
                    xivapi_mutex.unlock()
                    self.classjob_level_current_dict[classjob_id] -= 1
                    downloading_recipes = True
                if not self.running:
                    downloading_recipes = False
                    break
                else:
                    self.service_requests()
            if not downloading_recipes:
                break
            recipe: Recipe
            for recipe in self.process_todo_recipe_list:
                self.print_status(f"Worker waiting for universalis mutex")
                universalis_mutex.lock()
                self.print_status(
                    f"Getting recipe marketboard data for {recipe.ItemResult.Name}..."
                )
                get_profit(recipe, self.world)
                universalis_mutex.unlock()
                if not self.running:
                    downloading_recipes = False
                    break
                else:
                    self.service_requests()
            if not downloading_recipes or not self.running:
                break
            self.refresh_listings(self._processed_recipe_list)
            self._processed_recipe_list_mutex.lock()
            self._processed_recipe_list.extend(self.process_todo_recipe_list)
            self.update_table(self._processed_recipe_list)
            self._processed_recipe_list_mutex.unlock()
            self.process_todo_recipe_list.clear()
        self.print_status("Done")
        # TODO: Loop through listings to keep them fresh
        # QtCore.QThread.sleep(...)
        while self.running:
            self.refresh_listings(self._processed_recipe_list)
            sleep_ctr = 30
            while sleep_ctr > 0:
                QThread.sleep(1)
                sleep_ctr -= 1
                self.service_requests()

    def print_status(self, string: str) -> None:
        self.status_bar_update_signal.emit(string)

    def stop(self):
        print("exiting...")
        self.running = False

    @Slot(int, int)
    def set_classjob_level(self, classjob_id: int, classjob_level: int) -> None:
        self.classjob_level_max_dict[classjob_id] = classjob_level
