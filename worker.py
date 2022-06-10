from threading import Thread
from typing import Dict, List, Optional
from copy import copy
from PySide6.QtCore import Slot, Signal, QSize, QObject, QMutex, QSemaphore, QThread
from ff14marketcalc import get_profit
from universalis.universalis import get_listings

from xivapi.models import Recipe, RecipeCollection
from universalis.models import Listing
from xivapi.xivapi import get_recipes


class Worker(QObject):
    status_bar_update_signal = Signal(str)
    table_refresh_signal = Signal()
    refresh_recipe_request_sem = QSemaphore()

    def __init__(
        self, world: int, classjob_level_max_dict: Dict[int, int] = {}
    ) -> None:
        super().__init__()
        self.world = world
        self.classjob_level_max_dict: Dict[int, int] = classjob_level_max_dict
        self.classjob_level_current_dict: Dict[int, int] = {}
        self.process_todo_recipe_list: RecipeCollection = RecipeCollection()
        self._processed_recipe_list: RecipeCollection = RecipeCollection()
        self._processed_recipe_list_mutex = QMutex()
        self.xivapi_mutex = QMutex()
        self.universalis_mutex = QMutex()

        self.running = True

    @property
    def processed_recipe_list(self):
        self._processed_recipe_list_mutex.lock()
        r = copy(self._processed_recipe_list)
        self._processed_recipe_list_mutex.unlock()
        return r

    def refresh_listings(self, recipe_list: List[Recipe]) -> None:
        for recipe_index, recipe in enumerate(recipe_list):
            self.print_status(
                f"Refreshing marketboard data {recipe_index+1}/{len(recipe_list)} ({recipe.ItemResult.Name})..."
            )
            self.universalis_mutex.lock()
            get_listings(recipe.ItemResult.ID, self.world)
            self.universalis_mutex.unlock()
            if not self.running:
                break

    def service_requests(self):
        if self.refresh_recipe_request_sem.tryAcquire():
            self.refresh_listings(self.processed_recipe_list)
            self.table_refresh_signal.emit()

    def run(self):
        downloading_recipes = True
        while downloading_recipes:
            downloading_recipes = False
            for classjob_id in self.classjob_level_max_dict.keys():
                if (
                    classjob_level := self.classjob_level_current_dict.setdefault(
                        classjob_id, self.classjob_level_max_dict[classjob_id]
                    )
                ) > 0:
                    self.print_status(
                        f"Getting recipes for class {classjob_id} level {classjob_level}..."
                    )
                    self.xivapi_mutex.lock()
                    self.process_todo_recipe_list.extend(
                        get_recipes(
                            classjob_id=classjob_id, classjob_level=classjob_level
                        )
                    )
                    self.xivapi_mutex.unlock()
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
                self.print_status(
                    f"Getting recipe marketboard data for {recipe.ItemResult.Name}..."
                )
                self.universalis_mutex.lock()
                get_profit(recipe, self.world)
                self.universalis_mutex.unlock()
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
            self._processed_recipe_list_mutex.unlock()
            self.table_refresh_signal.emit()
            self.process_todo_recipe_list.clear()
        self.print_status("Done")
        # TODO: Loop through listings to keep them fresh
        # QtCore.QThread.sleep(...)
        while downloading_recipes and self.running:
            self.refresh_listings(self.process_todo_recipe_list)
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
