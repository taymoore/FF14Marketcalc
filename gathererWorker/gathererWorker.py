import json
import logging
from operator import mod
from pydantic import BaseModel
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
    QCoreApplication,
)
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QTableWidget,
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
from cache import PersistMapping, load_cache, save_cache
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
from xivapi.models import (
    ClassJob,
    GatheringItem,
    Item,
    Recipe,
    RecipeCollection,
    GatheringItemLevelConvertTable,
)
from xivapi.xivapi import (
    get_classjob_doh_list,
    get_page,
    get_recipe_by_id,
    get_recipes,
    search_recipes,
    get_content,
)
from xivapi.xivapi import save_to_disk as xivapi_save_to_disk


class GathererWorker(QThread):
    class GatheringItems(BaseModel):
        results_max: Optional[int]
        gathering_items: Dict[int, GatheringItem]

    status_bar_update_signal = Signal(str)

    def __init__(
        self,
        world_id: int,
        classjob_config_dict: Dict[int, ClassJobConfig],
        parent: Optional[QObject] = None,
    ) -> None:
        self.world_id = world_id

        self.classjob_config_dict = classjob_config_dict
        self.classjob_level_current_dict: Dict[int, int] = {}

        self.gathering_items_cache_filename = "gathering_items.bin"
        self.gathering_items = load_cache(
            self.gathering_items_cache_filename,
            GathererWorker.GatheringItems(gathering_items={}),
        )
        super().__init__(parent)

    # def update_table_item(self, )
    def print_status(self, text: str):
        self.status_bar_update_signal.emit(text)

    def yield_gathering_item(self) -> GatheringItem:
        if self.gathering_items.results_max is None:
            self.print_status(f"Getting pagination for gathering items...")
            page = get_page("GatheringItem", 1)
            self.gathering_items.results_max = page.Pagination.ResultsTotal
            gathering_item: GatheringItem = get_content(
                page.Results[0].Url, GatheringItem
            )
            self.gathering_items.gathering_items[gathering_item.ID] = gathering_item
            yield gathering_item
        for index in range(
            len(self.gathering_items.gathering_items), self.gathering_items.results_max
        ):
            self.print_status(
                f"Getting gathering item {index+1}/{self.gathering_items.results_max}..."
            )
            if not index % 100:
                page = get_page("GatheringItem", index % 100 + 1)
            gathering_item: GatheringItem = get_content(
                page.Results[index // 100].Url, GatheringItem
            )
            self.gathering_items.gathering_items[gathering_item.ID] = gathering_item
            yield gathering_item

    def run(self):
        print("Starting gatherer worker")
        while not self.isInterruptionRequested():
            for gathering_item in self.yield_gathering_item():
                QCoreApplication.processEvents()
                if self.isInterruptionRequested():
                    return

    def stop(self):
        print("Stopping gatherer worker")
        save_cache(self.gathering_items_cache_filename, self.gathering_items)
        self.requestInterruption()


class GathererWindow(QMainWindow):
    # class ItemsTableWidget(QTableWidget)
    def __init__(
        self,
        world_id: int,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.main_layout = QVBoxLayout()
        self.main_widget.setLayout(self.main_layout)
        self.classjob_level_layout = QHBoxLayout()
        self.main_layout.addLayout(self.classjob_level_layout)
        self.centre_splitter = QSplitter()
        self.main_layout.addWidget(self.centre_splitter)

        self.status_bar_label = QLabel()
        self.statusBar().addPermanentWidget(self.status_bar_label, 1)

        self.classjob_config_dict = PersistMapping[int, ClassJobConfig](
            "gatherer_classjob_config.bin"
        )
        for classjob_id in (16, 17):
            if classjob_id not in self.classjob_config_dict:
                classjob = get_content(f"ClassJob/{classjob_id}", ClassJob)
                self.classjob_config_dict[classjob_id] = ClassJobConfig(
                    **classjob.dict(), level=0
                )

        self.gatherer_worker = GathererWorker(
            world_id=world_id, classjob_config_dict=self.classjob_config_dict
        )
        self.gatherer_worker.status_bar_update_signal.connect(
            self.status_bar_label.setText
        )
        self.gatherer_worker.start()

    def closeEvent(self, event) -> None:
        print("exiting Gatherer...")
        self.classjob_config_dict.save_to_disk()
        self.gatherer_worker.stop()
        self.gatherer_worker.wait()
        super().closeEvent(event)
