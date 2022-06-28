from asyncio import gather
import json
import logging
import requests
from operator import mod
from pathlib import Path
from pydantic import BaseModel
from scipy import stats
from typing import Dict, List, Optional, Set, Tuple
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
from PySide6.QtGui import QBrush, QColor, QImage, QPixmap, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QSizePolicy,
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
    GatheringPoint,
    GatheringPointBase,
    Item,
    Recipe,
    RecipeCollection,
    TerritoryType,
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
    territory_table_update_signal = Signal(TerritoryType)
    set_map_image_signal = Signal(QPixmap)
    draw_gathering_point_signal = Signal(float, float, float)  # X, Y, radius

    def __init__(
        self,
        world_id: int,
        classjob_config_dict: Dict[int, ClassJobConfig],
        parent: Optional[QObject] = None,
    ) -> None:
        self.world_id = world_id

        self.auto_refresh_enabled = True
        self.user_selected_item_id = None
        self.user_selected_territory_id = None

        self.classjob_config_dict = classjob_config_dict
        self.classjob_level_current_dict: Dict[int, int] = {}

        self.gathering_items_cache_filename = "gathering_items.bin"
        self.gathering_items_dict = load_cache(
            self.gathering_items_cache_filename,
            GathererWorker.GatheringItems(gathering_items={}),
        )
        self.gathering_point_base_dict = PersistMapping[int, GatheringPointBase](
            "gathering_point_base.bin"
        )
        self.gathering_point_dict = PersistMapping[int, GatheringPoint](
            "gathering_point.bin"
        )
        self.territory_type_dict = PersistMapping[int, TerritoryType](
            "territory_type.bin"
        )
        # self.gathering_item_to_territory_dict: Dict[int, Set[int]] = {}
        # self.territory_to_gathering_item_dict: Dict[int, Set[int]] = {}
        self.territory_to_gathering_point_dict: Dict[int, Set[int]] = {}
        self.map_cache_dict: Dict[int, QPixmap] = {}
        super().__init__(parent)

    @Slot(bool)
    def set_auto_refresh(self, auto_refresh_enabled: bool) -> None:
        self.user_selected_item_id = None
        self.user_selected_territory_id = None
        self.auto_refresh_enabled = auto_refresh_enabled
        if self.auto_refresh_enabled:
            for gathering_item in self.gathering_items_dict.values():
                QCoreApplication.processEvents()
                if self.isInterruptionRequested():
                    return
                self.update_table_item(gathering_item)
                QCoreApplication.processEvents()
                if self.isInterruptionRequested():
                    return
                self.update_table_territory(gathering_item)

    def add_gathering_point_to_map(self, gathering_point: GatheringPoint) -> None:
        self.draw_gathering_point_signal.emit(
            gathering_point.ExportedGatheringPoint.X,
            gathering_point.ExportedGatheringPoint.Y,
            gathering_point.ExportedGatheringPoint.Radius,
        )

    @Slot(int)
    def update_map(self, territory_id: int) -> None:
        if territory_id in self.map_cache_dict:
            self.set_map_image_signal.emit(self.map_cache_dict[territory_id])
        else:
            territory_type = self.get_territory_type(territory_id)
            map_path = Path(f".data{territory_type.Map.MapFilename}")
            if not map_path.exists():
                map_path.parent.mkdir(parents=True, exist_ok=True)
                print(f"Downloading {territory_type.Map.MapFilename}")
                image_bytes = get_content(territory_type.Map.MapFilename)
                with open(map_path, "wb") as f:
                    f.write(image_bytes)
            else:
                with open(map_path, "rb") as f:
                    image_bytes = f.read()
            pixmap = QPixmap()
            pixmap.loadFromData(image_bytes)
            self.map_cache_dict[territory_id] = pixmap
            self.set_map_image_signal.emit(pixmap)
        for gathering_point_id in self.territory_to_gathering_point_dict[territory_id]:
            self.add_gathering_point_to_map(
                self.get_gathering_point(gathering_point_id)
            )

    def print_status(self, text: str):
        self.status_bar_update_signal.emit(text)

    def yield_gathering_item(self) -> GatheringItem:
        for gathering_item in self.gathering_items_dict.gathering_items.values():
            yield gathering_item
        page = get_page(
            "GatheringItem", self.gathering_items_dict.results_pulled // 100 + 1
        )
        self.gathering_items_dict.results_max = page.Pagination.ResultsTotal
        for index in range(
            self.gathering_items_dict.results_pulled,
            self.gathering_items_dict.results_max,
        ):
            self.print_status(
                f"Getting gathering item {index+1}/{self.gathering_items_dict.results_max}..."
            )
            if not index % 100:
                print(f"getting page {index//100+1}")
                page = get_page("GatheringItem", index // 100 + 1)
                self.gathering_items_dict.results_max = page.Pagination.ResultsTotal
            print(
                f"Getting item {index % 100} from page {self.gathering_items_dict.results_pulled // 100 + 1}"
            )
            gathering_item: GatheringItem = get_content(
                page.Results[index % 100].Url, GatheringItem
            )
            self.gathering_items_dict.results_pulled += 1
            if gathering_item.Item is None:
                continue
            self.gathering_items_dict.gathering_items[
                gathering_item.ID
            ] = gathering_item
            yield gathering_item

    def get_gathering_point_base(
        self, gathering_point_base_id: int
    ) -> GatheringPointBase:
        if gathering_point_base_id not in self.gathering_point_base_dict:
            self.gathering_point_base_dict[gathering_point_base_id] = get_content(
                f"GatheringPointBase/{gathering_point_base_id}", GatheringPointBase
            )
        return self.gathering_point_base_dict[gathering_point_base_id]

    def get_gathering_point(self, gathering_point_id: int) -> GatheringPoint:
        if gathering_point_id not in self.gathering_point_dict:
            self.gathering_point_dict[gathering_point_id] = get_content(
                f"GatheringPoint/{gathering_point_id}", GatheringPoint
            )
        return self.gathering_point_dict[gathering_point_id]

    def get_territory_type(self, territory_type_id: int) -> TerritoryType:
        if territory_type_id not in self.territory_type_dict:
            self.territory_type_dict[territory_type_id] = get_content(
                f"TerritoryType/{territory_type_id}", TerritoryType
            )
        return self.territory_type_dict[territory_type_id]

    def update_table_item(self, gathering_item: GatheringItem) -> None:
        listings = get_listings(gathering_item.Item.ID, self.world_id)
        assert gathering_item.GameContentLinks.GatheringPointBase is not None
        gathering_point_base_list = []
        for (
            gathering_point_base_id
        ) in (
            gathering_item.GameContentLinks.GatheringPointBase.yield_gathering_point_base_id()
        ):
            QCoreApplication.processEvents()
            if self.isInterruptionRequested():
                return
            # print(f"Getting gathering point base {gathering_point_base_id}")
            gathering_point_base_list.append(
                self.get_gathering_point_base(gathering_point_base_id)
            )
        profit = listings.minPrice * 0.95
        velocity = listings.regularSaleVelocity
        self.item_table_update_signal.emit(
            gathering_item, gathering_point_base_list, profit, velocity
        )

    def update_table_territory(self, gathering_item: GatheringItem) -> None:
        territory_type_set = set()
        for (
            gathering_point_base_id
        ) in (
            gathering_item.GameContentLinks.GatheringPointBase.yield_gathering_point_base_id()
        ):
            QCoreApplication.processEvents()
            if self.isInterruptionRequested():
                return
            gathering_point_base = self.get_gathering_point_base(
                gathering_point_base_id
            )
            for (
                gathering_point_id
            ) in (
                gathering_point_base.GameContentLinks.GatheringPoint.GatheringPointBase
            ):
                QCoreApplication.processEvents()
                if self.isInterruptionRequested():
                    return
                gathering_point = self.get_gathering_point(gathering_point_id)
                if gathering_point.TerritoryTypeTargetID == 1:
                    continue
                # QCoreApplication.processEvents()
                # if self.isInterruptionRequested():
                #     return
                territory_type = self.get_territory_type(
                    gathering_point.TerritoryTypeTargetID
                )
                territory_type_set.add(gathering_point.TerritoryTypeTargetID)
                self.territory_to_gathering_point_dict.setdefault(
                    territory_type.ID, set()
                ).add(gathering_point_id)
                # self.territory_to_gathering_item_dict.setdefault(
                #     territory_type.ID, set()
                # ).add(gathering_item.ID)
        # self.gathering_item_to_territory_dict.setdefault(
        #     gathering_item.ID, set()
        # ).update(territory_type_set)
        for territory_type_id in territory_type_set:
            self.territory_table_update_signal.emit(
                self.get_territory_type(territory_type_id)
            )

    def run(self):
        print("Starting gatherer worker")
        while not self.isInterruptionRequested():
            for gathering_item in self.yield_gathering_item():
                QCoreApplication.processEvents()
                if self.isInterruptionRequested():
                    return
                print("Updating table item")
                self.update_table_item(gathering_item)
                QCoreApplication.processEvents()
                if self.isInterruptionRequested():
                    return
                print("Updating table territory")
                self.update_table_territory(gathering_item)

    def stop(self):
        print("Stopping gatherer worker")
        save_cache(self.gathering_items_cache_filename, self.gathering_items_dict)
        self.gathering_point_base_dict.save_to_disk()
        self.gathering_point_dict.save_to_disk()
        self.territory_type_dict.save_to_disk()
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
                row.append(QTableWidgetItem(gathering_item.Item.Name))
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

    class TerritoryTableWidget(QTableWidget):
        update_map_signal = Signal(int)

        def __init__(self, parent: QWidget):
            super().__init__(parent)
            self.setColumnCount(1)
            self.setHorizontalHeaderLabels(["Name"])
            self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            self.verticalHeader().hide()
            self.setEditTriggers(QAbstractItemView.NoEditTriggers)

            self.table_data: Dict[int, List[QTableWidgetItem]] = {}

            self.cellClicked.connect(self.on_cell_clicked)

        def clear_contents(self) -> None:
            self.clearContents()
            self.setRowCount(0)
            self.table_data.clear()

        @Slot(TerritoryType)
        def on_item_table_update(
            self,
            territory_type: TerritoryType,
        ) -> None:
            if territory_type.ID not in self.table_data:
                row: List[QTableWidgetItem] = []
                row.append(QTableWidgetItem(territory_type.PlaceName.Name))
                self.insertRow(self.rowCount())
                self.setItem(self.rowCount() - 1, 0, row[0])
                self.table_data[territory_type.ID] = row
            self.sortItems(0, Qt.DescendingOrder)

        @Slot(int, int)
        def on_cell_clicked(self, row: int, column: int) -> None:
            print(f"Clicked on {self.item(row, column).text()}")
            for territory_id, row_data in self.table_data.items():
                if row_data[0].row() == row:
                    self.update_map_signal.emit(territory_id)
                    return
            print(f"Row {row} not found. Looking for {self.item(row, column).text()}")

    class Map(QWidget):
        def __init__(self):
            super().__init__()
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.pixmap = QPixmap()

            self.gathering_point_set: Set[Tuple[float, float, float]] = set()

        @Slot(str)
        def set_map_image(self, pixmap: QPixmap) -> None:
            # This will clear gathering point list
            print("Setting map image")
            self.gathering_point_set.clear()
            self.pixmap = pixmap
            self.update()

        @Slot(float, float, float)
        def add_gathering_point(self, x: float, y: float, radius: float) -> None:
            self.gathering_point_set.add((x, y, radius))
            self.update()

        def paintEvent(self, event: QPaintEvent) -> None:
            painter = QPainter(self)
            painter.drawPixmap(self.rect(), self.pixmap)
            if not self.pixmap.isNull():
                x_scale = self.width() / self.pixmap.width()
                y_scale = self.height() / self.pixmap.height()
                painter.setPen(QColor(0, 0, 255, 100))
                painter.setBrush(QColor(0, 0, 255, 50))
                for gathering_point in self.gathering_point_set:
                    x = (self.pixmap.width() / 2 + gathering_point[0]) * x_scale
                    y = (self.pixmap.height() / 2 + gathering_point[1]) * y_scale
                    x_radius = gathering_point[2] * x_scale
                    y_radius = gathering_point[2] * y_scale
                    painter.drawEllipse(x, y, x_radius, y_radius)
            super().paintEvent(event)

    set_auto_refresh_signal = Signal(bool)

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

        self.options_layout = QHBoxLayout()
        self.main_layout.addLayout(self.options_layout)

        self.refresh_button = QPushButton()
        self.refresh_button.setText("Refresh")
        self.refresh_button.clicked.connect(self.on_refresh_button_clicked)

        self.centre_splitter = QSplitter()
        self.main_layout.addWidget(self.centre_splitter)

        self.status_bar_label = QLabel()
        self.statusBar().addPermanentWidget(self.status_bar_label, 1)

        self.item_table = GathererWindow.ItemsTableWidget(self)
        self.centre_splitter.addWidget(self.item_table)

        self.territory_table = GathererWindow.TerritoryTableWidget(self)
        self.centre_splitter.addWidget(self.territory_table)
        # self.territory_table.cellClicked.connect(self.on_territory_table_cell_clicked)

        self.map = GathererWindow.Map()
        self.centre_splitter.addWidget(self.map)

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
        self.gatherer_worker.territory_table_update_signal.connect(
            self.territory_table.on_item_table_update
        )
        self.territory_table.update_map_signal.connect(self.gatherer_worker.update_map)
        self.set_auto_refresh_signal.connect(self.gatherer_worker.set_auto_refresh)
        self.gatherer_worker.set_map_image_signal.connect(self.map.set_map_image)
        self.gatherer_worker.draw_gathering_point_signal.connect(
            self.map.add_gathering_point
        )

        self.gatherer_worker.start(QThread.LowPriority)

    @Slot()
    def on_refresh_button_clicked(self):
        self.set_auto_refresh_signal.emit(True)

    # @Slot(int, int)
    # def on_territory_table_cell_clicked(self, row: int, column: int) -> None:
    #     pass

    def closeEvent(self, event) -> None:
        print("exiting Gatherer...")
        self.classjob_config_dict.save_to_disk()
        self.gatherer_worker.stop()
        self.gatherer_worker.wait()
        super().closeEvent(event)
