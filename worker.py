from typing import Dict, List, Optional, Tuple
from copy import copy
from PySide6.QtCore import Slot, Signal, QSize, QObject, QMutex, QSemaphore, QThread
from classjobConfig import ClassJobConfig
from ff14marketcalc import get_profit
from universalis.universalis import get_listings

from xivapi.models import ClassJob, Item, Recipe, RecipeCollection
from universalis.models import Listing, Listings
from xivapi.xivapi import get_classjob_doh_list, get_recipes


class Worker(QThread):
    status_bar_update_signal = Signal(str)
    table_refresh_signal = Signal()
    retainer_listings_changed = Signal(Listings)
    refresh_recipe_request_sem = QSemaphore()
    crafting_value_table_changed = Signal(dict)

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
        self._item_crafting_value_table: Dict[int, float] = {}
        self._item_crafting_value_table_mutex = QMutex()

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

    @property
    def item_crafting_value_table(self):
        self._item_crafting_value_table_mutex.lock()
        r = copy(self._item_crafting_value_table)
        self._item_crafting_value_table_mutex.unlock()
        return r

    def get_item_crafting_value_table(self) -> Dict[int, float]:
        return self.item_crafting_value_table

    def refresh_listings(self, recipe_list: List[Recipe]) -> None:
        for recipe_index, recipe in enumerate(recipe_list):
            self.print_status(
                f"Refreshing marketboard data {recipe_index+1}/{len(recipe_list)} ({recipe.ItemResult.Name})..."
            )
            listings: Listings = get_listings(recipe.ItemResult.ID, self.world)
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
                    get_profit(recipe, self.world, refresh_cache=False),
                    get_listings(
                        recipe.ItemResult.ID, self.world, cache_timeout_s=3600 * 24
                    ).regularSaleVelocity,
                    recipe,
                )
            )
        self._table_row_data.sort(key=lambda row: row[2] * row[3], reverse=True)
        self._table_row_data_mutex.unlock()
        self.table_refresh_signal.emit()

    def update_item_values(self, recipe_collection: RecipeCollection) -> None:
        def update_crafting_value_table(
            recipe: Recipe, crafting_value_table: Dict[int, float]
        ):
            for ingredient_index in range(9):
                quantity: int = getattr(recipe, f"AmountIngredient{ingredient_index}")
                item: Item = getattr(recipe, f"ItemIngredient{ingredient_index}")
                if not item:
                    break
                crafting_value_table[item.ID] = crafting_value_table.setdefault(
                    item.ID, 0
                ) + (
                    quantity
                    * float(item.LevelItem)
                    / self.classjob_level_max_dict[recipe.ClassJob.ID]
                )
                ingredient_recipes = getattr(
                    recipe, f"ItemIngredientRecipe{ingredient_index}"
                )
                if ingredient_recipes:
                    # take the recipe from the lowest level class
                    ingredient_recipe = min(
                        ingredient_recipes,
                        key=lambda ingredient_recipe: self.classjob_level_max_dict[
                            ingredient_recipe.ClassJob.ID
                        ],
                    )
                    update_crafting_value_table(ingredient_recipe, crafting_value_table)

        self._item_crafting_value_table_mutex.lock()
        self._item_crafting_value_table.clear()
        recipe: Recipe
        for recipe in recipe_collection:
            update_crafting_value_table(recipe, self._item_crafting_value_table)
        self._item_crafting_value_table_mutex.unlock()
        self.crafting_value_table_changed.emit(self._item_crafting_value_table)

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
                    self.process_todo_recipe_list.extend(
                        get_recipes(
                            classjob_id=classjob_id, classjob_level=classjob_level
                        )
                    )
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
                self.print_status(
                    f"Getting recipe marketboard data for {recipe.ItemResult.Name}..."
                )
                get_profit(recipe, self.world)
                if not self.running:
                    downloading_recipes = False
                    break
                else:
                    self.service_requests()
            if not downloading_recipes or not self.running:
                break
            self.print_status("Updating Crafting item value weights")
            self.update_item_values(self._processed_recipe_list)
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
        self.classjob_level_current_dict[classjob_id] = classjob_level
