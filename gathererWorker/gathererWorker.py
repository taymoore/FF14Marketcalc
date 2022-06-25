import json
import logging
from scipy import stats
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
import pyperclip
from PySide6.QtCore import (
    Slot,
    Signal,
    QSize,
    QThread,
    QSemaphore,
    Qt,
    QBasicTimer,
    QObject,
)
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QMainWindow,
    QLineEdit,
    QTextEdit,
    QLabel,
    QHeaderView,
    QAbstractItemView,
    QPushButton,
    QMenuBar,
    QWidgetAction,
    QSpinBox,
)
from pyqtgraph import (
    PlotWidget,
    DateAxisItem,
    AxisItem,
    PlotCurveItem,
    PlotDataItem,
    ViewBox,
    Point,
    functions,
    mkPen,
)
from QTableWidgetFloatItem import QTableWidgetFloatItem
from cache import PersistMapping
from classjobConfig import ClassJobConfig
from ff14marketcalc import get_profit, print_recipe
from itemCleaner.itemCleaner import ItemCleanerForm
from retainerWorker.models import ListingData
from universalis.models import Listings
from craftingWorker import CraftingWorker
from retainerWorker.retainerWorker import RetainerWorker
from universalis.universalis import (
    get_listings,
    set_seller_id,
)
from universalis.universalis import save_to_disk as universalis_save_to_disk
from xivapi.models import ClassJob, Item, Recipe, RecipeCollection
from xivapi.xivapi import (
    get_classjob_doh_list,
    get_recipe_by_id,
    get_recipes,
    search_recipes,
)
from xivapi.xivapi import save_to_disk as xivapi_save_to_disk


class GathererWorker(QThread):
    def __init__(
        self,
        world_id: int,
        classjob_config_dict: Dict[int, ClassJobConfig],
        parent: Optional[QObject] = ...,
    ) -> None:
        self.world_id = world_id
        self.classjob_config_dict = classjob_config_dict
        self.classjob_level_current_dict: Dict[int, int] = {}
        super().__init__(parent)

        self.gathering_item_dict = PersistMapping[int, Item](
            "gathering_items.bin"
        )  # item.ID -> item
        self.gathering_level_item_dict = PersistMapping[int, List[int]](
            "gathering_level_item.bin"
        )  # gatherer.level -> [item.ID]

    def run(self):
        print("Starting gatherer worker")
        while not self.isInterruptionRequested():
            for classjob in self.classjob_config_dict.values():
                if (
                    classjob_level := self.classjob_level_current_dict.setdefault(
                        classjob.ID, classjob.level
                    )
                ) > 0:
                    if len(self.gathering_level_item_dict[classjob_level]) > 0:
                        continue
                    self.print_status(
                        f"Getting items for {classjob.Abbreviation} level {classjob_level}..."
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


class GathererWindow(QMainWindow):
    def __init__(
        self, parent: Optional[QWidget] = ..., flags: Qt.WindowFlags = ...
    ) -> None:
        super().__init__(parent, flags)
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.main_layout = QVBoxLayout()
        self.main_widget.setLayout(self.main_layout)
        self.classjob_level_layout = QHBoxLayout()
        self.main_layout.addLayout(self.classjob_level_layout)
        self.centre_splitter = QSplitter()
        self.main_layout.addWidget(self.centre_splitter)
