import re
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
from ff14marketcalc import get_profit
from universalis.universalis import (
    get_listings,
    seller_id_in_listings,
    seller_id_in_recipe,
)

from xivapi.models import ClassJob, Item, Recipe, RecipeCollection
from universalis.models import Listing, Listings
from xivapi.xivapi import (
    get_classjob_doh_list,
    get_recipes,
    search_recipes,
    xivapi_mutex,
    yield_recipes,
)


class CraftingWorker(QThread):
    recipe_table_update_signal = Signal(
        Recipe, float, float
    )  # Recipe, profit, velocity
    status_bar_update_signal = Signal(str)
    seller_listings_matched_signal = Signal(Listings)

    def __init__(
        self,
        world_id: int,
        classjob_config_dict: Dict[int, ClassJobConfig],
        parent: Optional[QObject] = None,
    ) -> None:
        self.world_id = world_id
        self.classjob_config_dict = classjob_config_dict
        self.classjob_level_current_dict: Dict[int, int] = {}
        self.recipe_list = RecipeCollection()
        self.auto_refresh_listings = True
        super().__init__(parent)

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
            print(f"Found seller ID in recipe {recipe.ID}")
            self.seller_listings_matched_signal.emit(seller_listing)

    # Update the recipe table with the given recipe
    def update_table_recipe(self, recipe: Recipe) -> None:
        # print("Updating table recipes")
        self.emit_seller_id_in_recipe(recipe)
        # print(f"Getting profit for {recipe.ItemResult.Name}")
        profit = get_profit(recipe, self.world_id)
        # print(f"Getting velocity for {recipe.ItemResult.Name}")
        regularSaleVelocity = get_listings(
            recipe.ItemResult.ID, self.world_id
        ).regularSaleVelocity
        self.recipe_table_update_signal.emit(recipe, profit, regularSaleVelocity)

    # Search for recipes given by the user
    @Slot(str)
    def on_search_recipe(self, search_string: str) -> None:
        self.auto_refresh_listings = False
        print(f"Searching for '{search_string}'")
        recipes = search_recipes(search_string)
        if len(recipes) > 0:
            self.refresh_listings(recipes)

    # Refresh button clicked by user
    @Slot(bool)
    def on_set_auto_refresh_listings(self, refresh: bool) -> None:
        self.auto_refresh_listings = refresh
        if refresh:
            self.refresh_listings()

    # Refresh the listings for the current recipe list
    @Slot(list)
    def refresh_listings(self, recipe_list: List[Recipe] = None) -> None:
        recipe_list = recipe_list if recipe_list else self.recipe_list
        # print(f"Refreshing listings for {len(recipe_list)} recipes")
        for recipe_index, recipe in enumerate(recipe_list):
            self.print_status(
                f"Refreshing marketboard data {recipe_index+1}/{len(recipe_list)} ({recipe.ItemResult.Name})..."
            )
            QCoreApplication.processEvents()
            if self.isInterruptionRequested():
                return
            self.emit_seller_id_in_recipe(recipe)
            # TODO: If the recipe is in the database, we don't need to refresh it
            self.update_table_recipe(recipe)

    # Run the worker thread
    def run(self):
        print("Starting crafting worker")
        while not self.isInterruptionRequested():
            for classjob in self.classjob_config_dict.values():
                if (
                    classjob_level := self.classjob_level_current_dict.setdefault(
                        classjob.ID, classjob.level
                    )
                ) > 0:
                    self.print_status(
                        f"Getting recipes for {classjob.Abbreviation} level {classjob_level}..."
                    )
                    for recipe in yield_recipes(classjob.ID, classjob_level):
                        QCoreApplication.processEvents()
                        if self.isInterruptionRequested():
                            return
                        self.recipe_list.append(recipe)
                        self.print_status(
                            f"{classjob.Abbreviation} lvl {classjob_level}: Refreshing {recipe.ItemResult.Name}..."
                        )
                        self.update_table_recipe(recipe)
                    self.classjob_level_current_dict[classjob.ID] -= 1
                if self.auto_refresh_listings:
                    self.refresh_listings()
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
                    if self.isInterruptionRequested():
                        print("Interruption Received")
                        return

    def print_status(self, string: str) -> None:
        self.status_bar_update_signal.emit(string)

    def stop(self):
        print("Stopping crafting worker")
        self.requestInterruption()
        # self.quit()
