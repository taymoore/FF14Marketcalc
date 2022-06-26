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
    QCoreApplication,
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
from xivapi.models import (
    ClassJob,
    Item,
    Recipe,
    RecipeCollection,
    GatheringItemLevelConvertTable,
)
from xivapi.xivapi import (
    get_classjob_doh_list,
    get_recipe_by_id,
    get_recipes,
    search_recipes,
    get_content,
    yeild_content_page,
)
from xivapi.xivapi import save_to_disk as xivapi_save_to_disk


class GathererWorker(QThread):
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
        super().__init__(parent)

        self.gathering_item_dict = PersistMapping[int, Item](
            "gathering_items.bin"
        )  # item.ID -> item
        self.gathering_level_item_search_index = 0
        self.gathering_level_item_dict = PersistMapping[
            int, GatheringItemLevelConvertTable
        ](
            "gathering_level_item.bin"
        )  # gatherer.level -> GatheringItemLevelConvertTable

    # def update_table_item(self, )

    def get_gathering_item_level_table(
        self, jobclass_level: int
    ) -> GatheringItemLevelConvertTable:
        if jobclass_level in self.gathering_level_item_dict:
            return self.gathering_level_item_dict[jobclass_level]

    def run(self):
        print("Starting gatherer worker")
        while not self.isInterruptionRequested():
            for classjob in self.classjob_config_dict.values():
                if (
                    classjob_level := self.classjob_level_current_dict.setdefault(
                        classjob.ID, classjob.level
                    )
                ) > 0:
                    if classjob_level not in self.gathering_level_item_dict:
                        QCoreApplication.processEvents()
                        if self.isInterruptionRequested():
                            break
                        self.print_status(
                            f"Getting item list for {classjob.Abbreviation} level {classjob_level}..."
                        )
                        self.gathering_level_item_dict[classjob_level] = get_content(
                            f"GatheringItemLevelConvertTable/{classjob_level}",
                            GatheringItemLevelConvertTable,
                            snake_case=True,
                        )
                        self.print_status("")
                    for gatheringitem_id_index, gatheringitem_id in enumerate(
                        self.gathering_level_item_dict[
                            classjob_level
                        ].GameContentLinks.GatheringItem.GatheringItemLevel.values()
                    ):
                        if gatheringitem_id not in self.gathering_item_dict:
                            QCoreApplication.processEvents()
                            if self.isInterruptionRequested():
                                break
                            self.print_status(
                                f"Getting items for {classjob.Abbreviation} level {classjob_level} ({gatheringitem_id_index+1}/{len(self.gathering_level_item_dict[classjob_level].game_content_links.gathering_item.gathering_item_level)})..."
                            )
                            self.gathering_item_dict[gatheringitem_id] = get_content(
                                f"GatheringItem/{gatheringitem_id}", snake_case=True
                            )
                            self.print_status("")


class GathererWindow(QMainWindow):
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
