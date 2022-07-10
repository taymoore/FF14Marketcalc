import logging
import time
from typing import Dict, List, Optional, Tuple
from copy import copy
from PySide6.QtCore import (
    Slot,
    Signal,
    QSize,
    QObject,
    QMutex,
    QSemaphore,
    QThread,
    QCoreApplication,
)
from classjobConfig import ClassJobConfig
from ff14marketcalc import get_profit, log_time
from universalis.universalis import (
    get_listings,
    is_listing_expired,
    seller_id_in_recipe,
)

from xivapi.models import Recipe, RecipeCollection, Item
from universalis.models import Listings
from xivapi.xivapi import (
    get_item,
    search_recipes,
    yield_recipes,
)


class CraftingWorker(QObject):
    recipe_table_update_signal = Signal(
        Recipe, float, Listings
    )  # Recipe, profit, velocity
    status_bar_update_signal = Signal(str)
    seller_listings_matched_signal = Signal(Listings)
    crafting_value_table_changed = Signal(dict)

    def __init__(
        self,
        world_id: int,
        classjob_config_dict: Dict[int, ClassJobConfig],
        parent: Optional[QObject] = None,
    ) -> None:
        # _logger = logging.getLogger(__name__)
        self.abort = False
        self.world_id = world_id
        self.classjob_config_dict = classjob_config_dict
        self.classjob_level_current_dict: Dict[int, int] = {}
        self.recipe_list = RecipeCollection()
        self.auto_refresh_listings = True
        self._item_crafting_value_table: Dict[int, float] = {}
        self._item_crafting_value_table_mutex = QMutex()
        self._recipe_sent_to_table: List[int] = []
        super().__init__(parent)

    def get_item_crafting_value_table(self) -> Dict[int, float]:
        self._item_crafting_value_table_mutex.lock()
        r = copy(self._item_crafting_value_table)
        self._item_crafting_value_table_mutex.unlock()
        return r

    # Update the maximum classjob level
    @Slot(int, int)
    def set_classjob_level(self, classjob_id: int, classjob_level: int) -> None:
        self.classjob_config_dict[classjob_id].level = classjob_level
        self.classjob_level_current_dict[classjob_id] = classjob_level
        # print(f"Setting classjob {classjob_id} to level {classjob_level}")
        # Remove recipes above level
        recipe: Recipe
        recipes_to_remove = []
        for recipe in self.recipe_list:
            if (
                recipe.ClassJob.ID == classjob_id
                and recipe.RecipeLevelTable.ClassJobLevel > classjob_level
            ):
                recipes_to_remove.append(recipe)
        for recipe in recipes_to_remove:
            self.recipe_list.remove(recipe)

    def emit_seller_id_in_recipe(self, recipe: Recipe) -> None:
        for seller_listing in seller_id_in_recipe(recipe, self.world_id):
            print(
                f"Found seller ID in recipe {recipe.ItemResult.Name}: Item: {get_item(seller_listing.itemID).Name}"
            )
            self.seller_listings_matched_signal.emit(seller_listing)

    # Update the recipe table with the given recipe
    def update_table_recipe(self, recipe: Recipe) -> None:
        # print("Updating table recipes")
        self.emit_seller_id_in_recipe(recipe)
        # print(f"Getting profit for {recipe.ItemResult.Name}")
        profit = get_profit(recipe, self.world_id)
        # print(f"Getting velocity for {recipe.ItemResult.Name}")
        listings = get_listings(
            recipe.ItemResult.ID, self.world_id
        )
        self.recipe_table_update_signal.emit(recipe, profit, listings)

    # Search for recipes given by the user
    @Slot(str)
    def on_search_recipe(self, search_string: str) -> None:
        print(f"Searching for '{search_string}'")
        self._recipe_sent_to_table.clear()
        recipe_list = search_recipes(search_string)
        print(f"Found {len(recipe_list)} recipes")
        # if len(recipe_list) > 0:
        # self.refresh_listings(recipes, True)
        recipe: Recipe
        for recipe_index, recipe in enumerate(recipe_list):
            self._recipe_sent_to_table.append(recipe.ItemResult.ID)
            self.update_table_recipe(recipe)
        self.auto_refresh_listings = False

    # Refresh button clicked by user
    @Slot(bool)
    def on_set_auto_refresh_listings(self, refresh: bool) -> None:
        self.auto_refresh_listings = refresh
        if refresh:
            recipe: Recipe
            for recipe_index, recipe in enumerate(self.recipe_list):
                # self.print_status(
                #     f"Refreshing marketboard data {recipe_index+1}/{len(recipe_list)} ({recipe.ItemResult.Name})..."
                # )

                # QCoreApplication.processEvents()
                # if self.thread().isInterruptionRequested():
                #     return
                # if not self.auto_refresh_listings:
                #     return

                # t = time.time()
                if recipe.ItemResult.ID not in self._recipe_sent_to_table:
                    self._recipe_sent_to_table.append(recipe.ItemResult.ID)
                    self.update_table_recipe(recipe)
                # log_time(
                #     f"Refreshing marketboard data {recipe_index+1}/{len(self.recipe_list)} ({recipe.ItemResult.Name})",
                #     t,
                # )

    def is_recipe_expired(self, recipe: Recipe) -> bool:
        time_s = time.time()

        def _is_recipe_expired(recipe: Recipe, time_s: float) -> bool:
            if is_listing_expired(recipe.ItemResult.ID, self.world_id, time_s):
                # print(f"Recipe Result {recipe.ItemResult.Name} is expired")
                return True
            for ingredient_index in range(9):
                item: Item = getattr(recipe, f"ItemIngredient{ingredient_index}")
                if item:
                    if is_listing_expired(item.ID, self.world_id, time_s):
                        return True
                    item_recipe_list: Optional[Tuple[Recipe, ...]] = getattr(
                        recipe, f"ItemIngredientRecipe{ingredient_index}"
                    )
                    if item_recipe_list:
                        for item_recipe in item_recipe_list:
                            if _is_recipe_expired(item_recipe, time_s):
                                return True
            return False

        return _is_recipe_expired(recipe, time_s)

    # Refresh the listings for the current recipe list
    @Slot(list)
    def refresh_listings(
        self, recipe_list: List[Recipe] = None, force_refresh: bool = False
    ) -> None:
        recipe_list = recipe_list if recipe_list else self.recipe_list.copy()
        print(f"Refreshing listings for {len(recipe_list)} recipes")
        t = time.time()
        for recipe_index, recipe in enumerate(recipe_list):
            # self.print_status(
            #     f"Refreshing marketboard data {recipe_index+1}/{len(recipe_list)} ({recipe.ItemResult.Name})..."
            # )
            QCoreApplication.processEvents()
            if self.abort:
                return
            if not self.auto_refresh_listings and not force_refresh:
                print("Not auto refreshing listings")
                return
            # t = time.time()
            if recipe.ItemResult.ID not in self._recipe_sent_to_table or (
                self.is_recipe_expired(recipe) or force_refresh
            ):
                self._recipe_sent_to_table.append(recipe.ItemResult.ID)
                self.update_table_recipe(recipe)
                self.update_item_crafting_values(recipe)
            # log_time(
            #     f"Refreshing marketboard data {recipe_index+1}/{len(recipe_list)} ({recipe.ItemResult.Name})",
            #     t,
            # )
        log_time(f"Refreshing {len(recipe_list)} listings", t)

    def update_item_crafting_values(self, recipe: Recipe) -> None:
        def update_crafting_value_table(
            recipe: Recipe, crafting_value_table: Dict[int, float]
        ):
            for ingredient_index in range(9):
                QCoreApplication.processEvents()
                if self.abort:
                    return
                quantity: int = getattr(recipe, f"AmountIngredient{ingredient_index}")
                item: Item = getattr(recipe, f"ItemIngredient{ingredient_index}")
                if not item:
                    break
                crafting_value_table[item.ID] = crafting_value_table.setdefault(
                    item.ID, 0
                ) + (
                    quantity
                    * float(item.LevelItem)
                    / max(self.classjob_config_dict[recipe.ClassJob.ID].level, 1)
                )
                ingredient_recipes: Optional[Tuple[Recipe, ...]] = getattr(
                    recipe, f"ItemIngredientRecipe{ingredient_index}"
                )
                if ingredient_recipes:
                    # take the recipe from the lowest level class
                    ingredient_recipe = min(
                        ingredient_recipes,
                        key=lambda ingredient_recipe: self.classjob_config_dict[
                            ingredient_recipe.ClassJob.ID
                        ].level,
                    )
                    update_crafting_value_table(ingredient_recipe, crafting_value_table)

        self._item_crafting_value_table_mutex.lock()
        update_crafting_value_table(recipe, self._item_crafting_value_table)
        self._item_crafting_value_table_mutex.unlock()
        self.crafting_value_table_changed.emit(self._item_crafting_value_table)

    # Run the worker thread
    @Slot()
    def run(self):
        print("Starting crafting worker")
        while not self.abort:
            for classjob in self.classjob_config_dict.values():
                QCoreApplication.processEvents()
                if self.abort:
                    return
                if (
                    classjob_level := self.classjob_level_current_dict.setdefault(
                        classjob.ID, classjob.level
                    )
                ) > 0:
                    self.print_status(
                        f"Getting recipes for {classjob.Abbreviation} level {classjob_level}..."
                    )
                    # print(
                    #     f"Getting recipes for {classjob.Abbreviation} level {classjob_level}..."
                    # )
                    # t = time.time()
                    for recipe in yield_recipes(classjob.ID, classjob_level):
                        # print("polling for interrupt")
                        QCoreApplication.processEvents()
                        if self.abort:
                            print("Stopping crafting worker")
                            return
                        # print("interrupts processed")
                        self.recipe_list.append(recipe)
                        QCoreApplication.processEvents()
                        if self.abort:
                            print("Stopping crafting worker")
                            return
                        self.update_item_crafting_values(recipe)
                        # self.print_status(
                        #     f"{classjob.Abbreviation} lvl {classjob_level}: Refreshing {recipe.ItemResult.Name}..."
                        # )
                    self.classjob_level_current_dict[classjob.ID] -= 1
                    # t = log_time("Getting recipes", t)
                # t = time.time()
                if self.auto_refresh_listings:
                    self.refresh_listings()
                # t = log_time("Refreshing listings", t)
            if not any(
                current_level > 0
                for current_level in self.classjob_level_current_dict.values()
            ):
                print("No more recipes to get")
                sleep_ctr = 30
                while sleep_ctr > 0:
                    QThread.sleep(1)
                    sleep_ctr -= 1
                    if any(
                        current_level > 0
                        for current_level in self.classjob_level_current_dict.values()
                    ):
                        print("Recipes found, stopping sleep")
                        break
                    if self.abort:
                        print("Interruption Received")
                        return
        print("Stopping crafting worker")

    def print_status(self, string: str) -> None:
        self.status_bar_update_signal.emit(string)

    def stop(self):
        print("Stopping crafting worker")
        # self.thread().requestInterruption()
        self.abort = True
        # self.thread().quit()
