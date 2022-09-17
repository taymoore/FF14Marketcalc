from collections import defaultdict, deque
import enum
import logging
from re import I
import time
from typing import DefaultDict, Deque, Dict, Iterable, List, Optional, Set, Tuple
from copy import copy
from weakref import KeyedRef
import numpy as np
from PySide6.QtCore import (
    Slot,
    Signal,
    QSize,
    QObject,
    QMutex,
    QSemaphore,
    QThread,
    QCoreApplication,
    QThreadPool,
    QRunnable,
    QMutexLocker,
    Qt,
)
from classjobConfig import ClassJobConfig
from ff14marketcalc import GATHER_COST, get_profit, log_time
from universalis.universalis import (
    get_listings,
    is_listing_expired,
    seller_id_in_recipe,
)

from xivapi.models import Recipe, RecipeCollection, Item
from universalis.models import Listings
from xivapi.xivapi import (
    XivapiManager,
    get_item,
    search_recipes,
    yield_recipes,
)

_logger = logging.getLogger(__name__)
# _logger.setLevel(logging.DEBUG)


class CraftingWorker(QObject):
    class CraftingWorkerThread(QRunnable, QObject):
        set_row_data_signal = Signal(int, float, float, int)

        def __init__(
            self, crafting_worker: "CraftingWorker", parent: QObject = None
        ) -> None:
            self.crafting_worker = crafting_worker
            super().__init__(parent)

        @Slot()
        def run(self):
            exit_flag = False
            try:
                while not exit_flag:
                    with QMutexLocker(
                        self.crafting_worker.process_crafting_cost_queue_mutex
                    ):
                        item_id = (
                            self.crafting_worker.process_crafting_cost_queue.popleft()
                        )
                    self.process_crafting_cost(item_id, True)
            except IndexError as e:
                _logger.debug("CraftingWorkerThread: Finished processing")

        def process_crafting_cost(self, item_id: int, do_aquire_action=False) -> None:
            """
            do_aquire_action assumes the market_cost got updated before this was called and the aquire_cost may be outdated.
            """
            ingredient_item: Item
            crafting_cost: Optional[float] = np.inf
            # _logger.debug(f"process_crafting_cost: item_id: {item_id}")
            for recipe_id in self.crafting_worker.get_recipe_id_result_list(item_id):
                recipe_cost: Optional[float] = 0.0
                # _logger.debug(f"process_crafting_cost: recipe_id: {recipe_id}")
                recipe = self.crafting_worker.xivapi_manager.request_recipe(recipe_id)
                for ingredient_index in range(9):
                    if ingredient_item := getattr(
                        recipe, f"ItemIngredient{ingredient_index}"
                    ):
                        try:
                            ingredient_cost = self.crafting_worker.get_aquire_cost(
                                ingredient_item.ID
                            )
                        except KeyError:
                            # _logger.debug(
                            #     f"Cannot calculate crafting cost for {item_id}: {ingredient_item.ID} not in aquire_action_dict"
                            # )
                            ingredient_cost = None
                            break
                        else:
                            quantity: Optional[int] = getattr(
                                recipe, f"AmountIngredient{ingredient_index}"
                            )
                            assert quantity != None
                            ingredient_cost *= quantity
                            recipe_cost += ingredient_cost
                if recipe_cost is not None and recipe_cost > 0.0:
                    crafting_cost = min(crafting_cost, recipe_cost)
            # _logger.debug(f"Crafting cost for {item_id}: {crafting_cost}")
            try:
                crafting_cost_ = self.crafting_worker.get_crafting_cost(item_id)
            except KeyError:
                crafting_cost_ = None
            if crafting_cost is not None and crafting_cost != crafting_cost_:
                self.crafting_worker.set_crafting_cost(item_id, crafting_cost)
                do_aquire_action = True
            if do_aquire_action:
                self.process_aquire_action(item_id)

        def process_aquire_action(self, item_id: int) -> None:
            # _logger.debug(f"process_aquire_action: {item_id}")
            try:
                crafting_cost = self.crafting_worker.get_crafting_cost(item_id)
            except KeyError:
                crafting_cost = None
            try:
                market_cost = self.crafting_worker.get_market_cost(item_id)
            except KeyError:
                market_cost = None
            if market_cost is None:
                if crafting_cost is None:
                    self.crafting_worker.set_aquire_action(
                        item_id, CraftingWorker.AquireAction.GATHER
                    )
                    self.crafting_worker.set_aquire_cost(item_id, GATHER_COST)
                else:
                    self.crafting_worker.set_aquire_action(
                        item_id, CraftingWorker.AquireAction.CRAFT
                    )
                    self.crafting_worker.set_aquire_cost(item_id, crafting_cost)
            else:
                if crafting_cost is None:
                    self.crafting_worker.set_aquire_action(
                        item_id, CraftingWorker.AquireAction.BUY
                    )
                    self.crafting_worker.set_aquire_cost(item_id, market_cost)
                else:
                    if crafting_cost < market_cost:
                        self.crafting_worker.set_aquire_action(
                            item_id, CraftingWorker.AquireAction.CRAFT
                        )
                        self.crafting_worker.set_aquire_cost(item_id, crafting_cost)
                    else:
                        self.crafting_worker.set_aquire_action(
                            item_id, CraftingWorker.AquireAction.BUY
                        )
                        self.crafting_worker.set_aquire_cost(item_id, market_cost)
            for recipe_id in self.crafting_worker.get_recipe_id_ingredient_list(
                item_id
            ):
                recipe: Recipe
                recipe = self.crafting_worker.xivapi_manager.request_recipe(recipe_id)
                assert recipe is not None
                self.process_crafting_cost(recipe.ItemResult.ID)
            self.process_profit(item_id)

        def process_profit(self, item_id: int) -> None:
            # _logger.debug(f"process_profit: {item_id}")
            try:
                profit = self.crafting_worker.get_revenue(
                    item_id
                ) - self.crafting_worker.get_aquire_cost(item_id)
                for recipe_id in self.crafting_worker.get_recipe_id_result_list(
                    item_id
                ):
                    try:
                        profit_ = self.crafting_worker.get_profit(recipe_id)
                    except KeyError:
                        profit_ = None
                    if profit != profit_:
                        self.crafting_worker.set_profit(recipe_id, profit)
                        self.crafting_worker.set_profit_slot.emit(recipe_id, profit)
            except KeyError:
                return

    class AquireAction(enum.Enum):
        BUY = enum.auto()
        CRAFT = enum.auto()
        GATHER = enum.auto()

    set_profit_slot = Signal(int, float)

    def __init__(
        self,
        xivapi_manager: XivapiManager,
        set_profit_slot: Slot,
        parent: Optional[QObject] = None,
    ) -> None:
        self.xivapi_manager = xivapi_manager
        # self.set_row_data_slot = set_row_data_slot
        super().__init__(parent)
        self.set_profit_slot.connect(set_profit_slot)

        self.recipe_id_result_dict: DefaultDict[int, Set[int]] = defaultdict(set)
        self.recipe_id_result_mutex = QMutex()
        self.recipe_id_ingredient_dict: DefaultDict[int, Set[int]] = defaultdict(set)
        self.recipe_id_ingredient_mutex = QMutex()
        self.revenue_dict: Dict[int, float] = {}
        self.revenue_mutex = QMutex()
        self.market_cost_dict: Dict[int, float] = {}
        self.market_cost_mutex = QMutex()
        self.crafting_cost_dict: Dict[int, float] = {}
        self.crafting_cost_mutex = QMutex()
        self.aquire_cost_dict: Dict[int, float] = {}
        self.aquire_cost_mutex = QMutex()
        self.aquire_action_dict: Dict[int, CraftingWorker.AquireAction] = {}
        self.aquire_action_mutex = QMutex()
        self.profit_dict: Dict[int, float] = {}
        self.profit_mutex = QMutex()

        self.threadpool = QThreadPool(self)
        self.threadpool.setThreadPriority(QThread.LowPriority)
        self.process_crafting_cost_queue: Deque[int] = deque()
        self.process_crafting_cost_queue_mutex = QMutex()

    def queue_process_crafting_cost(self, item_id: int) -> None:
        with QMutexLocker(self.process_crafting_cost_queue_mutex):
            self.process_crafting_cost_queue.append(item_id)
            if (
                len(self.process_crafting_cost_queue) // 10
                - self.threadpool.activeThreadCount()
                >= 0
            ):
                # if len(self.process_crafting_cost_queue) > 1:
                #     _logger.info(
                #         f"Creating crafting worker thread. activeThreadCount: {self.threadpool.activeThreadCount()}; len(self.process_crafting_cost_queue): {len(self.process_crafting_cost_queue)}"
                #     )
                worker = CraftingWorker.CraftingWorkerThread(self)
                self.threadpool.start(worker)

    def get_recipe_id_result_list(self, item_id: int) -> Set[int]:
        with QMutexLocker(self.recipe_id_result_mutex):
            return copy(self.recipe_id_result_dict[item_id])

    def set_recipe_id_result(self, item_id: int, recipe_id: int) -> None:
        with QMutexLocker(self.recipe_id_result_mutex):
            self.recipe_id_result_dict[item_id].add(recipe_id)

    def get_recipe_id_ingredient_list(self, item_id: int) -> Set[int]:
        with QMutexLocker(self.recipe_id_ingredient_mutex):
            return copy(self.recipe_id_ingredient_dict[item_id])

    def set_recipe_id_ingredient(self, item_id: int, recipe_id: int) -> None:
        with QMutexLocker(self.recipe_id_ingredient_mutex):
            self.recipe_id_ingredient_dict[item_id].add(recipe_id)

    def get_revenue(self, item_id: int) -> float:
        with QMutexLocker(self.revenue_mutex):
            return self.revenue_dict[item_id]

    def set_revenue(self, item_id: int, revenue: float) -> None:
        with QMutexLocker(self.revenue_mutex):
            self.revenue_dict[item_id] = revenue

    def get_market_cost(self, item_id: int) -> float:
        with QMutexLocker(self.market_cost_mutex):
            return self.market_cost_dict[item_id]

    def set_market_cost(self, item_id: int, market_cost: float) -> None:
        with QMutexLocker(self.market_cost_mutex):
            self.market_cost_dict[item_id] = market_cost

    def get_crafting_cost(self, item_id: int) -> float:
        with QMutexLocker(self.crafting_cost_mutex):
            return self.crafting_cost_dict[item_id]

    def set_crafting_cost(self, item_id: int, crafting_cost: float) -> None:
        with QMutexLocker(self.crafting_cost_mutex):
            self.crafting_cost_dict[item_id] = crafting_cost

    def get_aquire_cost(self, item_id: int) -> float:
        with QMutexLocker(self.aquire_cost_mutex):
            return self.aquire_cost_dict[item_id]

    def set_aquire_cost(self, item_id: int, aquire_cost: float) -> None:
        with QMutexLocker(self.aquire_cost_mutex):
            self.aquire_cost_dict[item_id] = aquire_cost

    def get_aquire_action(self, item_id: int) -> AquireAction:
        with QMutexLocker(self.aquire_action_mutex):
            return self.aquire_action_dict[item_id]

    def set_aquire_action(self, item_id: int, aquire_action: AquireAction) -> None:
        with QMutexLocker(self.aquire_action_mutex):
            self.aquire_action_dict[item_id] = aquire_action

    def set_profit(self, recipe_id: int, profit: float) -> None:
        with QMutexLocker(self.profit_mutex):
            self.profit_dict[recipe_id] = profit

    def get_profit(self, recipe_id: int) -> float:
        with QMutexLocker(self.profit_mutex):
            return self.profit_dict[recipe_id]


# class CraftingWorker_(QObject):
#     recipe_table_update_signal = Signal(
#         Recipe, float, float, int
#     )  # Recipe, profit, velocity
#     status_bar_update_signal = Signal(str)
#     seller_listings_matched_signal = Signal(Listings)
#     crafting_value_table_changed = Signal(dict)

#     def __init__(
#         self,
#         world_id: int,
#         classjob_config_dict: Dict[int, ClassJobConfig],
#         parent: Optional[QObject] = None,
#     ) -> None:
#         # _logger = logging.getLogger(__name__)
#         self.abort = False
#         self.world_id = world_id
#         self.classjob_config_dict = classjob_config_dict
#         self.classjob_level_current_dict: Dict[int, int] = {}
#         self.recipe_list = RecipeCollection()
#         self.auto_refresh_listings = True
#         self._item_crafting_value_table: Dict[int, float] = {}
#         self._item_crafting_value_table_mutex = QMutex()
#         self._recipe_sent_to_table: List[int] = []
#         super().__init__(parent)

#     def get_item_crafting_value_table(self) -> Dict[int, float]:
#         self._item_crafting_value_table_mutex.lock()
#         r = copy(self._item_crafting_value_table)
#         self._item_crafting_value_table_mutex.unlock()
#         return r

#     # Update the maximum classjob level
#     @Slot(int, int)
#     def set_classjob_level(self, classjob_id: int, classjob_level: int) -> None:
#         self.classjob_config_dict[classjob_id].level = classjob_level
#         self.classjob_level_current_dict[classjob_id] = classjob_level
#         # print(f"Setting classjob {classjob_id} to level {classjob_level}")
#         # Remove recipes above level
#         recipe: Recipe
#         recipes_to_remove = []
#         for recipe in self.recipe_list:
#             if (
#                 recipe.ClassJob.ID == classjob_id
#                 and recipe.RecipeLevelTable.ClassJobLevel > classjob_level
#             ):
#                 recipes_to_remove.append(recipe)
#         for recipe in recipes_to_remove:
#             self.recipe_list.remove(recipe)

#     def emit_seller_id_in_recipe(self, recipe: Recipe) -> None:
#         for seller_listing in seller_id_in_recipe(recipe, self.world_id):
#             print(
#                 f"Found seller ID in recipe {recipe.ItemResult.Name}: Item: {get_item(seller_listing.itemID).Name}"
#             )
#             self.seller_listings_matched_signal.emit(seller_listing)

#     # Update the recipe table with the given recipe
#     def update_table_recipe(self, recipe: Recipe) -> None:
#         # print("Updating table recipes")
#         self.emit_seller_id_in_recipe(recipe)
#         # print(f"Getting profit for {recipe.ItemResult.Name}")
#         profit = get_profit(recipe, self.world_id)
#         # print(f"Getting velocity for {recipe.ItemResult.Name}")
#         listings = get_listings(recipe.ItemResult.ID, self.world_id)
#         self.recipe_table_update_signal.emit(
#             recipe, profit, listings.regularSaleVelocity, len(listings.listings)
#         )

#     # Search for recipes given by the user
#     @Slot(str)
#     def on_search_recipe(self, search_string: str) -> None:
#         print(f"Searching for '{search_string}'")
#         self._recipe_sent_to_table.clear()
#         recipe_list = search_recipes(search_string)
#         print(f"Found {len(recipe_list)} recipes")
#         # if len(recipe_list) > 0:
#         # self.refresh_listings(recipes, True)
#         recipe: Recipe
#         for recipe_index, recipe in enumerate(recipe_list):
#             self._recipe_sent_to_table.append(recipe.ItemResult.ID)
#             self.update_table_recipe(recipe)
#         self.auto_refresh_listings = False

#     # Refresh button clicked by user
#     @Slot(bool)
#     def on_set_auto_refresh_listings(self, refresh: bool) -> None:
#         self.auto_refresh_listings = refresh
#         if refresh:
#             recipe: Recipe
#             for recipe_index, recipe in enumerate(self.recipe_list):
#                 # self.print_status(
#                 #     f"Refreshing marketboard data {recipe_index+1}/{len(recipe_list)} ({recipe.ItemResult.Name})..."
#                 # )

#                 # QCoreApplication.processEvents()
#                 # if self.thread().isInterruptionRequested():
#                 #     return
#                 # if not self.auto_refresh_listings:
#                 #     return

#                 # t = time.time()
#                 if recipe.ItemResult.ID not in self._recipe_sent_to_table:
#                     self._recipe_sent_to_table.append(recipe.ItemResult.ID)
#                     self.update_table_recipe(recipe)
#                 # log_time(
#                 #     f"Refreshing marketboard data {recipe_index+1}/{len(self.recipe_list)} ({recipe.ItemResult.Name})",
#                 #     t,
#                 # )

#     def is_recipe_expired(self, recipe: Recipe) -> bool:
#         time_s = time.time()

#         def _is_recipe_expired(recipe: Recipe, time_s: float) -> bool:
#             if is_listing_expired(recipe.ItemResult.ID, self.world_id, time_s):
#                 # print(f"Recipe Result {recipe.ItemResult.Name} is expired")
#                 return True
#             for ingredient_index in range(9):
#                 item: Item = getattr(recipe, f"ItemIngredient{ingredient_index}")
#                 if item:
#                     if is_listing_expired(item.ID, self.world_id, time_s):
#                         return True
#                     item_recipe_list: Optional[Tuple[Recipe, ...]] = getattr(
#                         recipe, f"ItemIngredientRecipe{ingredient_index}"
#                     )
#                     if item_recipe_list:
#                         for item_recipe in item_recipe_list:
#                             if _is_recipe_expired(item_recipe, time_s):
#                                 return True
#             return False

#         return _is_recipe_expired(recipe, time_s)

#     # Refresh the listings for the current recipe list
#     @Slot(list)
#     def refresh_listings(
#         self, recipe_list: List[Recipe] = None, force_refresh: bool = False
#     ) -> None:
#         recipe_list = recipe_list if recipe_list else self.recipe_list.copy()
#         # print(f"Refreshing listings for {len(recipe_list)} recipes")
#         num_of_recipes_updated = 0
#         t = time.time()
#         for recipe_index, recipe in enumerate(recipe_list):
#             # self.print_status(
#             #     f"Refreshing marketboard data {recipe_index+1}/{len(recipe_list)} ({recipe.ItemResult.Name})..."
#             # )
#             QCoreApplication.processEvents()
#             if self.abort:
#                 return
#             if not self.auto_refresh_listings and not force_refresh:
#                 print("Not auto refreshing listings")
#                 return
#             # t = time.time()
#             if recipe.ItemResult.ID not in self._recipe_sent_to_table or (
#                 self.is_recipe_expired(recipe) or force_refresh
#             ):
#                 self._recipe_sent_to_table.append(recipe.ItemResult.ID)
#                 self.update_table_recipe(recipe)
#                 self.update_item_crafting_values(recipe)
#                 if self.is_recipe_expired(recipe):
#                     num_of_recipes_updated += 1
#             # log_time(
#             #     f"Refreshing marketboard data {recipe_index+1}/{len(recipe_list)} ({recipe.ItemResult.Name})",
#             #     t,
#             # )
#         if num_of_recipes_updated > 0:
#             log_time(f"Refreshing {num_of_recipes_updated} listings", t)

#     def update_item_crafting_values(self, recipe: Recipe) -> None:
#         def update_crafting_value_table(
#             recipe: Recipe, crafting_value_table: Dict[int, float]
#         ):
#             for ingredient_index in range(9):
#                 QCoreApplication.processEvents()
#                 if self.abort:
#                     return
#                 quantity: int = getattr(recipe, f"AmountIngredient{ingredient_index}")
#                 item: Item = getattr(recipe, f"ItemIngredient{ingredient_index}")
#                 if not item:
#                     break
#                 crafting_value_table[item.ID] = crafting_value_table.setdefault(
#                     item.ID, 0
#                 ) + (
#                     quantity
#                     * float(item.LevelItem)
#                     / max(self.classjob_config_dict[recipe.ClassJob.ID].level, 1)
#                 )
#                 ingredient_recipes: Optional[Tuple[Recipe, ...]] = getattr(
#                     recipe, f"ItemIngredientRecipe{ingredient_index}"
#                 )
#                 if ingredient_recipes:
#                     # take the recipe from the lowest level class
#                     ingredient_recipe = min(
#                         ingredient_recipes,
#                         key=lambda ingredient_recipe: self.classjob_config_dict[
#                             ingredient_recipe.ClassJob.ID
#                         ].level,
#                     )
#                     update_crafting_value_table(ingredient_recipe, crafting_value_table)

#         self._item_crafting_value_table_mutex.lock()
#         update_crafting_value_table(recipe, self._item_crafting_value_table)
#         self._item_crafting_value_table_mutex.unlock()
#         self.crafting_value_table_changed.emit(self._item_crafting_value_table)

#     # Run the worker thread
#     @Slot()
#     def run(self):
#         print("Starting crafting worker")
#         while not self.abort:
#             for classjob in self.classjob_config_dict.values():
#                 QCoreApplication.processEvents()
#                 if self.abort:
#                     return
#                 if (
#                     classjob_level := self.classjob_level_current_dict.setdefault(
#                         classjob.ID, classjob.level
#                     )
#                 ) > 0:
#                     self.print_status(
#                         f"Getting recipes for {classjob.Abbreviation} level {classjob_level}..."
#                     )
#                     # print(
#                     #     f"Getting recipes for {classjob.Abbreviation} level {classjob_level}..."
#                     # )
#                     # t = time.time()
#                     for recipe in yield_recipes(classjob.ID, classjob_level):
#                         # print("polling for interrupt")
#                         QCoreApplication.processEvents()
#                         if self.abort:
#                             print("Stopping crafting worker")
#                             return
#                         # print("interrupts processed")
#                         self.recipe_list.append(recipe)
#                         QCoreApplication.processEvents()
#                         if self.abort:
#                             print("Stopping crafting worker")
#                             return
#                         self.update_item_crafting_values(recipe)
#                         # self.print_status(
#                         #     f"{classjob.Abbreviation} lvl {classjob_level}: Refreshing {recipe.ItemResult.Name}..."
#                         # )
#                     self.classjob_level_current_dict[classjob.ID] -= 1
#                     # t = log_time("Getting recipes", t)
#                 # t = time.time()
#                 if self.auto_refresh_listings:
#                     self.refresh_listings()
#                 # t = log_time("Refreshing listings", t)
#             if not any(
#                 current_level > 0
#                 for current_level in self.classjob_level_current_dict.values()
#             ):
#                 print("No more recipes to get")
#                 sleep_ctr = 30
#                 while sleep_ctr > 0:
#                     QThread.sleep(1)
#                     sleep_ctr -= 1
#                     if any(
#                         current_level > 0
#                         for current_level in self.classjob_level_current_dict.values()
#                     ):
#                         print("Recipes found, stopping sleep")
#                         break
#                     if self.abort:
#                         print("Interruption Received")
#                         return
#         print("Stopping crafting worker")

#     def print_status(self, string: str) -> None:
#         self.status_bar_update_signal.emit(string)

#     def stop(self):
#         print("Stopping crafting worker")
#         # self.thread().requestInterruption()
#         self.abort = True
#         # self.thread().quit()
