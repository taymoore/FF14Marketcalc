from threading import Thread
from typing import Dict, List, Optional
from PySide6.QtCore import Slot, Signal, QSize, QObject, QMutex, QSemaphore
from ff14marketcalc import get_profit
from universalis.universalis import get_listings

from xivapi.models import Recipe, RecipeCollection
from universalis.models import Listing
from xivapi.xivapi import get_recipes


class Worker(QObject):
    status_bar_update_signal = Signal(str)

    def __init__(
        self, world: int, classjob_level_max_dict: Dict[int, int] = {}
    ) -> None:
        super().__init__()
        self.world = world
        self.classjob_level_max_dict: Dict[int, int] = classjob_level_max_dict
        self.classjob_level_current_dict: Dict[int, int] = {}
        self.process_todo_recipe_list: RecipeCollection = RecipeCollection()
        self.processed_recipe_list: RecipeCollection = RecipeCollection()
        # self.process_listings_list: List[Listing] = []

        self.xivapi_mutex = QMutex()
        self.universalis_mutex = QMutex()

        self.running = True

    def run(self):
        downloading_recipes = True
        while downloading_recipes:
            downloading_recipes = False
            for classjob_id, classjob_level_max in self.classjob_level_max_dict.items():
                if (
                    classjob_level := self.classjob_level_current_dict.setdefault(
                        classjob_id, 1
                    )
                ) < classjob_level_max:
                    self.print_status(
                        f"Getting class {classjob_id} level {classjob_level}..."
                    )
                    self.xivapi_mutex.lock()
                    self.process_todo_recipe_list.extend(
                        get_recipes(
                            classjob_id=classjob_id, classjob_level=classjob_level
                        )
                    )
                    self.xivapi_mutex.unlock()
                    self.classjob_level_current_dict[classjob_id] += 1
                    downloading_recipes = True
                if not self.running:
                    downloading_recipes = False
                    break
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
            self.processed_recipe_list.extend(self.process_todo_recipe_list)
            self.process_todo_recipe_list.clear()
        self.print_status("Done")

    def print_status(self, string: str) -> None:
        self.status_bar_update_signal.emit(string)

    def stop(self):
        print("exiting...")
        self.running = False

    @Slot(int, int)
    def set_classjob_level(self, classjob_id: int, classjob_level: int) -> None:
        self.classjob_level_max_dict[classjob_id] = classjob_level
