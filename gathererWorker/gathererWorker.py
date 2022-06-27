from asyncio import gather
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
    GatheringPointBase,
    Item,
    Recipe,
    RecipeCollection,
)
from xivapi.xivapi import (
    get_classjob_doh_list,
    get_page,
    get_recipe_by_id,
    get_recipes,
    search_recipes,
    get_content,
)


class GathererWorker(QThread):
    class GatheringItems(BaseModel):
        results_max: Optional[int]
        results_pulled: int = 0
        gathering_items: Dict[int, GatheringItem]

    status_bar_update_signal = Signal(str)
    item_table_update_signal = Signal(GatheringItem, list, float, float)

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
        self.gathering_point_base_dict = PersistMapping[int, GatheringPointBase](
            "gathering_point_base.bin"
        )
        super().__init__(parent)

    def print_status(self, text: str):
        self.status_bar_update_signal.emit(text)

    def yield_gathering_item(self) -> GatheringItem:
        for gathering_item in self.gathering_items.gathering_items.values():
            yield gathering_item
        page = get_page("GatheringItem", self.gathering_items.results_pulled // 100 + 1)
        self.gathering_items.results_max = page.Pagination.ResultsTotal
        for index in range(
            self.gathering_items.results_pulled, self.gathering_items.results_max
        ):
            self.print_status(
                f"Getting gathering item {index+1}/{self.gathering_items.results_max}..."
            )
            if not index % 100:
                print(f"getting page {index//100+1}")
                page = get_page("GatheringItem", index // 100 + 1)
                self.gathering_items.results_max = page.Pagination.ResultsTotal
            print(
                f"Getting item {index % 100} from page {self.gathering_items.results_pulled // 100 + 1}"
            )
            gathering_item: GatheringItem = get_content(
                page.Results[index % 100].Url, GatheringItem
            )
            self.gathering_items.results_pulled += 1
            if gathering_item.Item is None:
                continue
            self.gathering_items.gathering_items[gathering_item.ID] = gathering_item
            yield gathering_item

    def update_table_item(self, gathering_item: GatheringItem) -> None:
        listings = get_listings(gathering_item.Item.ID, self.world_id)
        assert gathering_item.GameContentLinks.GatheringPointBase is not None
        gathering_point_base_list = []
        for (
            gathering_point_base_id
        ) in (
            gathering_item.GameContentLinks.GatheringPointBase.yield_gathering_point_base_id()
        ):
            if gathering_point_base_id not in self.gathering_point_base_dict:
                QCoreApplication.processEvents()
                if self.isInterruptionRequested():
                    return
                self.gathering_point_base_dict[gathering_point_base_id] = get_content(
                    f"GatheringPointBase/{gathering_point_base_id}", GatheringPointBase
                )
            gathering_point_base_list.append(
                self.gathering_point_base_dict[gathering_point_base_id]
            )
        profit = listings.minPrice * 0.95
        velocity = listings.regularSaleVelocity
        self.item_table_update_signal.emit(
            gathering_item, gathering_point_base_list, profit, velocity
        )

    def run(self):
        print("Starting gatherer worker")
        while not self.isInterruptionRequested():
            for gathering_item in self.yield_gathering_item():
                QCoreApplication.processEvents()
                if self.isInterruptionRequested():
                    return
                self.update_table_item(gathering_item)

    def stop(self):
        print("Stopping gatherer worker")
        save_cache(self.gathering_items_cache_filename, self.gathering_items)
        self.gathering_point_base_dict.save_to_disk()
        self.requestInterruption()


class GathererWindow(QMainWindow):
    class ItemsTableWidget(QTableWidget):
        def __init__(self, parent: QWidget):
            super().__init__(parent)
            self.setColumnCount(6)
            self.setHorizontalHeaderLabels(
                ["Bot", "Min", "Item", "Profit", "Velocity", "Score"]
            )
            self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            self.verticalHeader().hide()
            self.setEditTriggers(QAbstractItemView.NoEditTriggers)

            # item_id -> row
            self.table_data: Dict[int, List[QTableWidgetItem]] = {}

        def clear_contents(self) -> None:
            self.clearContents()
            self.setRowCount(0)
            self.table_data.clear()

        @Slot(GatheringItem, list, float, float)
        def on_item_table_update(
            self,
            gathering_item: GatheringItem,
            gathering_point_base_list: List[GatheringPointBase],
            profit: float,
            velocity: float,
        ) -> None:
            if gathering_item.ID in self.table_data:
                row = self.table_data[gathering_item.ID]
                row[3].setText(f"{profit:,.0f}")
                row[4].setText(f"{velocity:.2f}")
                row[5].setText(f"{profit * velocity:,.0f}")
            else:
                row: List[QTableWidgetItem] = []
                bot_lvl = None
                min_lvl = None
                try:
                    for gathering_point_base in gathering_point_base_list:
                        if (
                            gathering_point_base.GatheringTypeTargetID == 1
                            or gathering_point_base.GatheringTypeTargetID == 3
                        ):
                            if bot_lvl is None:
                                for (
                                    __gathering_item
                                ) in gathering_point_base.yield_gathering_items():
                                    if __gathering_item.ID == gathering_item.ID:
                                        bot_lvl = (
                                            __gathering_item.GatheringItemLevel.GatheringItemLevel
                                        )
                                        break
                        elif (
                            gathering_point_base.GatheringTypeTargetID == 0
                            or gathering_point_base.GatheringTypeTargetID == 2
                        ):
                            if min_lvl is None:
                                for (
                                    __gathering_item
                                ) in gathering_point_base.yield_gathering_items():
                                    if __gathering_item.ID == gathering_item.ID:
                                        min_lvl = (
                                            __gathering_item.GatheringItemLevel.GatheringItemLevel
                                        )
                                        break
                        else:
                            raise Exception(
                                f"Unknown gathering type target ID {gathering_point_base.GatheringTypeTargetID} for gathering point base {gathering_point_base.ID}"
                            )
                    assert bot_lvl is not None or min_lvl is not None
                except AssertionError as e:
                    print(f"Error: {e}")
                    print(f"Gathering item {gathering_item.ID}")
                    raise e

                row.append(
                    QTableWidgetItem(f"{bot_lvl}" if bot_lvl is not None else "")
                )
                row.append(
                    QTableWidgetItem(f"{min_lvl}" if min_lvl is not None else "")
                )
                row.append(QTableWidgetFloatItem(gathering_item.Item.Name))
                row.append(QTableWidgetFloatItem(f"{profit:,.0f}"))
                row.append(QTableWidgetFloatItem(f"{velocity:.2f}"))
                row.append(QTableWidgetFloatItem(f"{profit * velocity:,.0f}"))
                self.insertRow(self.rowCount())
                self.setItem(self.rowCount() - 1, 0, row[0])
                self.setItem(self.rowCount() - 1, 1, row[1])
                self.setItem(self.rowCount() - 1, 2, row[2])
                self.setItem(self.rowCount() - 1, 3, row[3])
                self.setItem(self.rowCount() - 1, 4, row[4])
                self.setItem(self.rowCount() - 1, 5, row[5])
                self.table_data[gathering_item.ID] = row
            self.sortItems(5, Qt.DescendingOrder)

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

        self.item_table = GathererWindow.ItemsTableWidget(self)
        self.main_layout.addWidget(self.item_table)

        # Workers
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
        self.gatherer_worker.item_table_update_signal.connect(
            self.item_table.on_item_table_update
        )

        self.gatherer_worker.start()

    def closeEvent(self, event) -> None:
        print("exiting Gatherer...")
        self.classjob_config_dict.save_to_disk()
        self.gatherer_worker.stop()
        self.gatherer_worker.wait()
        super().closeEvent(event)
