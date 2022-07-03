from asyncio import gather
import json
import logging
import requests
from operator import mod
from pathlib import Path
from pydantic import BaseModel
from scipy import stats
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import pandas as pd
import numpy as np
import pyperclip
from PySide6.QtCore import (
    QItemSelection,
    QRegularExpression,
    QSortFilterProxyModel,
    Slot,
    Signal,
    QSize,
    QThread,
    QSemaphore,
    Qt,
    QBasicTimer,
    QObject,
    QCoreApplication,
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
)
from PySide6.QtGui import QBrush, QColor, QImage, QPixmap, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QTableView,
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

_logger = logging.getLogger(__name__)


class GathererWorker(QThread):
    class GatheringItems(BaseModel):
        results_max: int = 0
        results_pulled: int = 0
        gathering_items: Dict[int, GatheringItem]

    status_bar_update_signal = Signal(str)
    item_table_update_signal = Signal(GatheringItem, list, float, float)
    territory_table_update_signal = Signal(TerritoryType)
    set_map_image_signal = Signal(QPixmap)
    draw_gathering_point_signal = Signal(float, float, float)  # X, Y, radius
    gathering_item_to_territory_changed_signal = Signal(dict)
    territory_to_gathering_item_changed_signal = Signal(dict)

    def __init__(
        self,
        world_id: int,
        classjob_config_dict: PersistMapping[int, ClassJobConfig],
        parent: Optional[QObject] = None,
    ) -> None:
        self.world_id = world_id

        # self.auto_refresh_enabled = True
        # self.user_selected_item_id = None
        # self.user_selected_territory_id = None

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
        # self.territory_to_gathering_item_dict: Dict[int, Set[int]] = {}
        self.territory_to_gathering_item_dict: Dict[int, Set[int]] = {}
        self.territory_to_gathering_point_dict: Dict[int, Set[int]] = {}
        self.gathering_item_to_territory_dict: Dict[int, Set[int]] = {}
        self.gathering_item_to_gathering_point_dict: Dict[int, Set[int]] = {}
        # self.territory_to_gathering_items_dict: Dict[int, Set[int]] = {}
        self.map_cache_dict: Dict[int, QPixmap] = {}
        self.selected_territory_id: Optional[int] = None
        self.gathering_item_filter_set: Set[int] = set()
        super().__init__(parent)

    # @Slot(bool)
    # def set_auto_refresh(self, auto_refresh_enabled: bool) -> None:
    #     self.user_selected_item_id = None
    #     self.user_selected_territory_id = None
    # self.auto_refresh_enabled = auto_refresh_enabled
    # if self.auto_refresh_enabled:
    #     for gathering_item in self.gathering_items_dict.gathering_items.values():
    #         QCoreApplication.processEvents()
    #         if self.isInterruptionRequested():
    #             return
    #         self.update_table_item(gathering_item)
    #         QCoreApplication.processEvents()
    #         if self.isInterruptionRequested():
    #             return
    #         self.update_table_territory(gathering_item)

    @Slot(int)
    def gathering_item_filter_added(self, gathering_item_id: int) -> None:
        print(f"gathering_item_filter_added: {gathering_item_id}")
        if gathering_item_id not in self.gathering_item_filter_set:
            self.gathering_item_filter_set.add(gathering_item_id)
            if self.selected_territory_id:
                self.update_map(self.selected_territory_id)

    @Slot(int)
    def gathering_item_filter_removed(self, gathering_item_id: int) -> None:
        print(f"gathering_item_filter_removed: {gathering_item_id}")
        if gathering_item_id in self.gathering_item_filter_set:
            self.gathering_item_filter_set.remove(gathering_item_id)
            if self.selected_territory_id:
                self.update_map(self.selected_territory_id)

    @Slot()
    def gathering_item_filter_cleared(self) -> None:
        print(f"Clearing gathering item filter")
        if len(self.gathering_item_filter_set) > 0:
            self.gathering_item_filter_set.clear()
            if self.selected_territory_id:
                self.update_map(self.selected_territory_id)

    # @Slot(set)
    # def gathering_item_filter_changed(self, gathering_item_id_set: set) -> None:
    #     if self.gathering_item_filter_set != gathering_item_id_set:
    #         print(f"gathering_item_filter_changed: {gathering_item_id_set}")
    #         self.gathering_item_filter_set = gathering_item_id_set
    #         if self.selected_territory_id:
    #             self.update_map(self.selected_territory_id)

    @Slot(int)
    def update_map(self, territory_id: int) -> None:
        self.selected_territory_id = territory_id
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
            gathering_point = self.get_gathering_point(gathering_point_id)
            if (
                gathering_point.ExportedGatheringPoint
                and gathering_point.ExportedGatheringPoint.Radius > 0
                and (
                    len(self.gathering_item_filter_set) == 0
                    or any(
                        gathering_point_id
                        in self.gathering_item_to_gathering_point_dict[
                            gathering_item_id
                        ]
                        for gathering_item_id in self.gathering_item_filter_set
                    )
                )
            ):
                # if any(
                #     gathering_point_id
                #     in self.gathering_item_to_gathering_point_dict[gathering_item_id]
                #     for gathering_item_id in self.gathering_item_filter_set
                # ):
                #     print(f"{gathering_point_id} is in filter")
                # elif len(self.gathering_item_filter_set) > 0:
                #     print(f"gathering_point_id {gathering_point_id} is not in filter")
                #     print(f"gathering_item_filter_set {self.gathering_item_filter_set}")
                #     print(
                #         f"gathering_item_to_gathering_point_dict {self.gathering_item_to_gathering_point_dict}"
                #     )
                self.draw_gathering_point_signal.emit(
                    gathering_point.ExportedGatheringPoint.X,
                    gathering_point.ExportedGatheringPoint.Y,
                    gathering_point.ExportedGatheringPoint.Radius,
                )

    def print_status(self, text: str):
        self.status_bar_update_signal.emit(text)

    def yield_gathering_item(self) -> GatheringItem:
        for _gathering_item in self.gathering_items_dict.gathering_items.values():
            # if _gathering_item.GameContentLinks.GatheringPointBase is None:
            #     del self.gathering_items_dict.gathering_items[_gathering_item.ID]
            #     continue
            yield _gathering_item
        # TODO: if self.gathering_items_dict.results_max == self.gathering_items_dict.results_pulled:
        # Consider defaults to 0
        # return
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
            if gathering_item.GameContentLinks.GatheringPointBase is None:
                print(
                    f"ERROR: Item {gathering_item.Item.Name} has no GatheringPointBase"
                )
                print(f"Gathering Item ID: {gathering_item.ID}")
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
        update_map = False
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
            if gathering_point_base.GameContentLinks.GatheringPoint is None:
                # print(
                #     f"Gathering Point Base ID {gathering_point_base.ID} has no GatheringPoint"
                # )
                continue
            for (
                gathering_point_id
            ) in (
                gathering_point_base.GameContentLinks.GatheringPoint.GatheringPointBase
            ):
                QCoreApplication.processEvents()
                if self.isInterruptionRequested():
                    return
                gathering_point = self.get_gathering_point(gathering_point_id)
                if gathering_point.TerritoryTypeTargetID <= 1:
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
                if (
                    territory_type.ID
                    not in self.gathering_item_to_territory_dict.setdefault(
                        gathering_item.ID, set()
                    )
                ):
                    self.gathering_item_to_territory_dict[gathering_item.ID].add(
                        territory_type.ID
                    )
                    self.gathering_item_to_territory_changed_signal.emit(
                        self.gathering_item_to_territory_dict
                    )
                if (
                    gathering_point_id
                    not in self.gathering_item_to_gathering_point_dict.setdefault(
                        gathering_item.ID, set()
                    )
                ):
                    self.gathering_item_to_gathering_point_dict[gathering_item.ID].add(
                        gathering_point_id
                    )
                    update_map = True
                if (
                    gathering_item.ID
                    not in self.territory_to_gathering_item_dict.setdefault(
                        territory_type.ID, set()
                    )
                ):
                    self.territory_to_gathering_item_dict[territory_type.ID].add(
                        gathering_item.ID
                    )
                    self.territory_to_gathering_item_changed_signal.emit(
                        self.territory_to_gathering_item_dict
                    )

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
        if update_map and self.selected_territory_id:
            self.update_map(self.selected_territory_id)

    def run(self):
        print("Starting gatherer worker")
        for gathering_item in self.yield_gathering_item():
            QCoreApplication.processEvents()
            if self.isInterruptionRequested():
                return
            # print("Updating table item")
            self.update_table_item(gathering_item)
            QCoreApplication.processEvents()
            if self.isInterruptionRequested():
                return
            # print("Updating table territory")
            self.update_table_territory(gathering_item)

    def stop(self):
        print("Stopping gatherer worker")
        save_cache(self.gathering_items_cache_filename, self.gathering_items_dict)
        self.gathering_point_base_dict.save_to_disk()
        self.gathering_point_dict.save_to_disk()
        self.territory_type_dict.save_to_disk()
        self.requestInterruption()


class GathererWindow(QMainWindow):
    class ItemTableView(QTableView):
        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            self.verticalHeader().hide()
            self.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.setSelectionMode(QAbstractItemView.MultiSelection)
            self.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.setSortingEnabled(True)
            self.sortByColumn(5, Qt.DescendingOrder)

    class ItemTableProxyModel(QSortFilterProxyModel):
        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self.setDynamicSortFilter(True)
            # self.territory_to_gathering_item_dict: Dict[int, Set[int]] = {}
            # self.selected_territory_set: Set[int] = set()
            self.gathering_item_id_filter_set: Set[int] = set()

        def lessThan(self, left, right):
            leftData = self.sourceModel().data(left, Qt.UserRole)
            rightData = self.sourceModel().data(right, Qt.UserRole)
            return leftData < rightData

        def filterAcceptsRow(
            self,
            source_row: int,
            source_parent: Union[QModelIndex, QPersistentModelIndex],
        ) -> bool:
            source_model = self.sourceModel()
            assert isinstance(source_model, GathererWindow.ItemTableModel)
            if (
                len(self.gathering_item_id_filter_set) == 0
                or source_model.table_data[source_row][-1]
                in self.gathering_item_id_filter_set
            ):
                return super().filterAcceptsRow(source_row, source_parent)
            return False

        def set_gathering_id_filter(
            self, gathering_item_id_filter_set: Set[int]
        ) -> None:
            if self.gathering_item_id_filter_set != gathering_item_id_filter_set:
                self.gathering_item_id_filter_set = gathering_item_id_filter_set
                self.invalidateFilter()

        # def invalidateRowsFilter(self) -> None:
        #     gathering_item_filter_set: Set[int] = set()
        #     for territory_id in self.selected_territory_set:
        #         gathering_item_filter_set.update(
        #             self.territory_to_gathering_item_dict[territory_id]
        #         )
        #     if gathering_item_filter_set != self.gathering_item_filter_set:
        #         self.gathering_item_filter_set = gathering_item_filter_set
        #         return super().invalidateRowsFilter()

        # @Slot(dict)
        # def on_territory_to_gathering_item_dict_changed(
        #     self, territory_to_gathering_item_dict: Dict[int, Set[int]]
        # ) -> None:
        #     self.territory_to_gathering_item_dict = territory_to_gathering_item_dict
        #     self.invalidateRowsFilter()

        # def set_territory_filter(self, territory_set: Set[int]) -> None:
        #     if territory_set != self.selected_territory_set:
        #         print(f"Territory filter updated")
        #         self.selected_territory_set = territory_set
        #         self.invalidateRowsFilter()

        # def add_territory_filter(self, territory_id: int) -> None:
        #     if territory_id not in self.selected_territory_set:
        #         print(f"Territory filter added: {territory_id}")
        #         self.selected_territory_set.add(territory_id)
        #         self.invalidateRowsFilter()

        # def remove_territory_filter(self, territory_id: int) -> None:
        #     if territory_id in self.selected_territory_set:
        #         print(f"Territory filter removed: {territory_id}")
        #         self.selected_territory_set.remove(territory_id)
        #         self.invalidateRowsFilter()

        # @Slot(set)
        # def on_territory_selection_changed(self, territory_id_set: Set[int]) -> None:
        #     print(f"Territory selection changed: {territory_id_set}")
        #     if self.selected_territory_set != territory_id_set:
        #         self.selected_territory_set = territory_id_set
        #         self.invalidateRowsFilter()

    class ItemTableModel(QAbstractTableModel):
        def __init__(self, parent: Optional[QObject] = None) -> None:
            super().__init__(parent)
            self.table_data: List[List[Any]] = []
            self.gathering_item_row_data: Dict[int, List[Any]] = {}
            self.header_data: List[str] = [
                "Bot",
                "Min",
                "Item",
                "Profit",
                "Velocity",
                "Score",
            ]

        def rowCount(
            self, parent: Union[QModelIndex, QPersistentModelIndex] = None
        ) -> int:
            return len(self.table_data)

        def columnCount(
            self, parent: Union[QModelIndex, QPersistentModelIndex] = None
        ) -> int:
            return 6

        def data(  # type: ignore[override]
            self,
            index: QModelIndex,
            role: Qt.ItemDataRole = Qt.DisplayRole,
        ) -> Any:
            if not index.isValid():
                return None
            if role == Qt.DisplayRole:
                cell_data = self.table_data[index.row()][index.column()]
                if index.column() == 3 or index.column() == 5:
                    return f"{cell_data:,.0f}"
                elif index.column() == 4:
                    return f"{cell_data:,.2f}"
                elif index.column() <= 1:
                    return cell_data if cell_data else ""
                else:
                    return cell_data
            elif role == Qt.UserRole:
                return self.table_data[index.row()][index.column()]
            return None

        def headerData(  # type: ignore[override]
            self,
            section: int,
            orientation: Qt.Orientation,
            role: Qt.ItemDataRole = Qt.DisplayRole,
        ) -> Optional[str]:
            if orientation == Qt.Horizontal and role == Qt.DisplayRole:
                return self.header_data[section]
            return None

        @Slot(GatheringItem, list, float, float)
        def on_item_table_update(
            self,
            gathering_item: GatheringItem,
            gathering_point_base_list: List[GatheringPointBase],
            profit: float,
            velocity: float,
        ) -> None:
            row: List[Any]
            if gathering_item.ID in self.gathering_item_row_data:
                row = self.gathering_item_row_data[gathering_item.ID]
                row[3].setText(f"{profit:,.0f}")
                row[4].setText(f"{velocity:.2f}")
                row[5].setText(f"{profit * velocity:,.0f}")
            else:
                row = []
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

                # TODO: Use widget items here?
                row.append(bot_lvl)
                row.append(min_lvl)
                row.append(gathering_item.Item.Name)
                row.append(profit)
                row.append(velocity)
                row.append(profit * velocity)
                row.append(gathering_item.ID)
                self.beginInsertRows(QModelIndex(), self.rowCount(), self.rowCount())
                self.table_data.append(row)
                self.gathering_item_row_data[gathering_item.ID] = row
                self.endInsertRows()

    class TerritoryTableView(QTableView):
        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            self.verticalHeader().hide()
            self.setEditTriggers(QAbstractItemView.NoEditTriggers)
            # self.setSortingEnabled(True)

    class TerritoryTableProxyModel(QSortFilterProxyModel):
        def __init__(self, parent: Optional[QWidget] = None) -> None:
            super().__init__(parent)
            self.setDynamicSortFilter(True)
            self.setFilterCaseSensitivity(Qt.CaseInsensitive)
            # self.gathering_item_to_territory_dict: Dict[
            #     int, Set[int]
            # ] = {}  # key: gathering_item.ID, value: territory_type.ID
            # self.gathering_item_id_filter_set: Set[int] = set()
            self.territory_id_filter_set: Set[int] = set()

        def filterAcceptsRow(
            self,
            source_row: int,
            source_parent: Union[QModelIndex, QPersistentModelIndex],
        ) -> bool:
            source_model = self.sourceModel()
            assert isinstance(source_model, GathererWindow.TerritoryTableModel)
            if (
                len(self.territory_id_filter_set) == 0
                or source_model.table_data[source_row][-1]
                in self.territory_id_filter_set
            ):
                return super().filterAcceptsRow(source_row, source_parent)
            return False

        def set_territory_id_filter(self, territory_id_filter_set: Set[int]) -> None:
            if self.territory_id_filter_set != territory_id_filter_set:
                self.territory_id_filter_set = territory_id_filter_set
                self.invalidateFilter()

        # def invalidateRowsFilter(self) -> None:
        #     territory_filter_set: Set[int] = set()
        #     for gathering_item_id in self.gathering_item_id_filter_set:
        #         territory_filter_set.update(
        #             self.gathering_item_to_territory_dict[gathering_item_id]
        #         )
        #     if territory_filter_set != self.territory_filter_set:
        #         self.territory_filter_set = territory_filter_set
        #         return super().invalidateRowsFilter()

        # @Slot(dict)
        # def on_gathering_item_to_territory_dict_changed(
        #     self, gathering_item_to_territory_dict: Dict[int, Set[int]]
        # ) -> None:
        #     self.gathering_item_to_territory_dict = gathering_item_to_territory_dict
        #     self.invalidateRowsFilter()

        # def gathering_item_filter_added(self, gathering_item_id: int) -> None:
        #     if gathering_item_id not in self.gathering_item_filter_set:
        #         print(f"Gathering item filter added: {gathering_item_id}")
        #         self.gathering_item_filter_set.add(gathering_item_id)
        #         self.invalidateRowsFilter()

        # def gathering_item_filter_removed(self, gathering_item_id: int) -> None:
        #     if gathering_item_id in self.gathering_item_filter_set:
        #         print(f"Gathering item filter removed: {gathering_item_id}")
        #         self.gathering_item_filter_set.remove(gathering_item_id)
        #         self.invalidateRowsFilter()

        # @Slot(set)
        # def on_gathering_item_selection_changed(
        #     self, gathering_item_id_set: Set[int]
        # ) -> None:
        #     if self.gathering_item_filter_set != gathering_item_id_set:
        #         print(f"Item selection changed: {gathering_item_id_set}")
        #         self.gathering_item_filter_set = gathering_item_id_set
        #         self.invalidateRowsFilter()

    class TerritoryTableModel(QAbstractTableModel):
        def __init__(self, parent: Optional[QObject] = None) -> None:
            super().__init__(parent)
            self.table_data: List[List[Union[QTableWidgetItem, int]]] = []
            self.header_data: List[str] = ["Name"]

        def rowCount(
            self, parent: Union[QModelIndex, QPersistentModelIndex] = None
        ) -> int:
            return len(self.table_data)

        def columnCount(
            self, parent: Union[QModelIndex, QPersistentModelIndex] = None
        ) -> int:
            return 1

        def data(  # type: ignore[override]
            self,
            index: QModelIndex,
            role: Qt.ItemDataRole = Qt.DisplayRole,
        ) -> Optional[Union[QTableWidgetItem, int]]:
            if not index.isValid():
                return None
            if role == Qt.DisplayRole:
                try:
                    return self.table_data[index.row()][index.column()]
                except KeyError as e:
                    print(f"row: {index.row()} column: {index.column()}")
                    print(f"Table data: {self.table_data}")
                    raise e
            return None

        def headerData(  # type: ignore[override]
            self,
            section: int,
            orientation: Qt.Orientation,
            role: Qt.ItemDataRole = Qt.DisplayRole,
        ) -> Optional[str]:
            if orientation == Qt.Horizontal and role == Qt.DisplayRole:
                return self.header_data[section]
            return None

        @Slot(TerritoryType)
        def on_item_table_update(
            self,
            territory_type: TerritoryType,
        ) -> None:
            if any(territory_type.ID == row_data[-1] for row_data in self.table_data):
                return
            self.beginInsertRows(QModelIndex(), self.rowCount(), self.rowCount())
            # row: List[Union[QTableWidgetItem, int]] = []
            row_data = []
            row_data.append(territory_type.PlaceName.Name)
            row_data.append(territory_type.ID)
            self.table_data.append(row_data)
            self.endInsertRows()
            # self.sortItems(0, Qt.DescendingOrder)

    class Map(QWidget):
        def __init__(self):
            super().__init__()
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            self.pixmap = QPixmap()

            self.gathering_point_set: Set[Tuple[float, float, float]] = set()

        @Slot(str)
        def set_map_image(self, pixmap: QPixmap) -> None:
            # This will clear gathering point list
            # print("Setting map image")
            # TODO: Don't need to redraw all the time
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

    # set_auto_refresh_signal = Signal(bool)
    update_map_signal = Signal(int)
    # territory_selection_changed_signal = Signal(set)
    # item_selection_changed_signal = Signal(set)
    gathering_item_filter_added_signal = Signal(set)
    gathering_item_filter_removed_signal = Signal(set)
    gathering_item_filter_cleared_signal = Signal()

    def __init__(
        self,
        world_id: int,
        parent: Optional[QWidget] = None,
    ) -> None:
        self.selected_territory_id_set: Set[int] = set()
        self.selected_gathering_item_id_set: Set[int] = set()
        self.territory_id_filter_set: Set[int] = set()
        self.gathering_item_id_filter_set: Set[int] = set()
        self.gathering_item_to_territory_dict: Dict[
            int, Set[int]
        ] = {}  # key: gathering_item.ID, value: territory_type.ID
        self.territory_to_gathering_item_dict: Dict[
            int, Set[int]
        ] = {}  # key: territory_type.ID, value: gathering_item.ID
        super().__init__(parent)
        # self.setWindowFlags(Qt.WindowStaysOnBottomHint)
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.main_layout = QVBoxLayout()
        self.main_widget.setLayout(self.main_layout)

        self.options_layout = QHBoxLayout()
        self.main_layout.addLayout(self.options_layout)

        self.refresh_button = QPushButton()
        self.options_layout.addWidget(self.refresh_button)
        self.refresh_button.setText("Refresh")
        self.refresh_button.clicked.connect(self.on_refresh_button_clicked)  # type: ignore

        self.territory_search_lineedit = QLineEdit()
        self.options_layout.addWidget(self.territory_search_lineedit)

        self.centre_splitter = QSplitter()
        self.main_layout.addWidget(self.centre_splitter)

        self.status_bar_label = QLabel()
        self.statusBar().addPermanentWidget(self.status_bar_label, 1)

        # self.item_table = GathererWindow.ItemsTableWidget(self)
        self.item_table_model = GathererWindow.ItemTableModel(self)
        self.item_table_proxy_model = GathererWindow.ItemTableProxyModel(self)
        self.item_table_proxy_model.setSourceModel(self.item_table_model)
        # self.item_table_proxy_model.sort(4, Qt.DescendingOrder)
        self.item_table_view = GathererWindow.ItemTableView(self)
        self.item_table_view.setModel(self.item_table_proxy_model)
        self.item_table_view.clicked.connect(self.on_item_table_clicked)  # type: ignore
        self.centre_splitter.addWidget(self.item_table_view)
        # self.item_table_view.selectionModel().selectionChanged.connect(self.on_gathering_item_selection_changed)  # type: ignore

        # self.territory_table = GathererWindow.TerritoryTableWidget_(self)
        # TODO: Review delegate for sorting unique https://stackoverflow.com/questions/53324931/qsortfilterproxymodel-by-column-value
        self.territory_table_model = GathererWindow.TerritoryTableModel(self)
        self.territory_table_view = GathererWindow.TerritoryTableView(self)
        self.territory_table_proxy_model = GathererWindow.TerritoryTableProxyModel(self)
        self.territory_table_proxy_model.sort(0, Qt.AscendingOrder)
        self.territory_search_lineedit.textChanged.connect(  # type: ignore
            self.territory_table_proxy_model.setFilterRegularExpression
        )
        # self.gathering_item_filter_added_signal.connect(
        #     self.territory_table_proxy_model.gathering_item_filter_added
        # )
        # self.gathering_item_filter_removed_signal.connect(
        #     self.territory_table_proxy_model.gathering_item_filter_removed
        # )
        self.territory_table_proxy_model.setSourceModel(self.territory_table_model)
        self.territory_table_view.setModel(self.territory_table_proxy_model)
        self.centre_splitter.addWidget(self.territory_table_view)
        self.territory_table_view.clicked.connect(  # type: ignore
            self.on_territory_table_clicked
        )
        # self.territory_table_view.selectionModel().selectionChanged.connect(self.on_territory_selection_changed)  # type: ignore
        # self.territory_selection_changed_signal.connect(
        #     self.item_table_proxy_model.on_territory_selection_changed
        # )
        # self.item_selection_changed_signal.connect(
        #     self.territory_table_proxy_model.on_gathering_item_selection_changed
        # )

        self.map = GathererWindow.Map()
        self.centre_splitter.addWidget(self.map)

        self.setMinimumSize(QSize(1000, 600))

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
            self.item_table_model.on_item_table_update
        )
        self.gatherer_worker.territory_table_update_signal.connect(
            self.territory_table_model.on_item_table_update
        )
        self.update_map_signal.connect(self.gatherer_worker.update_map)
        # self.set_auto_refresh_signal.connect(self.gatherer_worker.set_auto_refresh)
        self.gatherer_worker.set_map_image_signal.connect(self.map.set_map_image)
        self.gatherer_worker.draw_gathering_point_signal.connect(
            self.map.add_gathering_point
        )
        self.gatherer_worker.gathering_item_to_territory_changed_signal.connect(
            self.on_gathering_item_to_territory_dict_changed
        )
        self.gathering_item_filter_added_signal.connect(
            self.gatherer_worker.gathering_item_filter_added
        )
        self.gathering_item_filter_removed_signal.connect(
            self.gatherer_worker.gathering_item_filter_removed
        )
        self.gathering_item_filter_cleared_signal.connect(
            self.gatherer_worker.gathering_item_filter_cleared
        )
        self.gatherer_worker.territory_to_gathering_item_changed_signal.connect(
            self.on_territory_to_gathering_item_dict_changed
        )

        self.gatherer_worker.start(QThread.LowPriority)

    @Slot()
    def on_refresh_button_clicked(self):
        self.territory_table_view.selectionModel().clearSelection()
        self.item_table_view.selectionModel().clearSelection()
        QCoreApplication.processEvents()
        self.selected_gathering_item_id_set.clear()
        self.update_gathering_item_filter()
        self.selected_territory_id_set.clear()
        self.update_territory_filter()
        self.gathering_item_filter_cleared_signal.emit()
        # self.set_auto_refresh_signal.emit(True)

    @Slot(QModelIndex)
    def on_item_table_clicked(self, table_view_item: QModelIndex):
        print(
            f"Clicked on {table_view_item.row()} {table_view_item.column()}, {table_view_item.data()}"
        )
        table_data_item = self.item_table_proxy_model.mapToSource(table_view_item)
        print(
            f"Data item: {table_data_item.row()} {table_data_item.column()}, {table_data_item.data()}"
        )

        gathering_item_id = self.item_table_model.table_data[table_data_item.row()][-1]
        if table_view_item in self.item_table_view.selectedIndexes():
            print(
                f"Adding {gathering_item_id} to {self.selected_gathering_item_id_set}"
            )
            self.selected_gathering_item_id_set.add(gathering_item_id)
            # self.territory_table_proxy_model.gathering_item_filter_added(
            #     gathering_item_id
            # )
            self.update_territory_filter()
            self.gathering_item_filter_added_signal.emit(gathering_item_id)
        else:
            print(
                f"Removing {gathering_item_id} from {self.selected_gathering_item_id_set}"
            )
            self.selected_gathering_item_id_set.discard(gathering_item_id)
            # self.territory_table_proxy_model.gathering_item_filter_removed(
            #     gathering_item_id
            # )
            self.update_territory_filter()
            self.gathering_item_filter_removed_signal.emit(gathering_item_id)

    @Slot(QModelIndex)
    def on_territory_table_clicked(self, table_view_item: QModelIndex) -> None:
        print(
            f"Clicked on {table_view_item.row()} {table_view_item.column()}, {table_view_item.data()}"
        )
        table_data_item = self.territory_table_proxy_model.mapToSource(table_view_item)
        print(
            f"Data item: {table_data_item.row()} {table_data_item.column()}, {table_data_item.data()}"
        )
        territory_id = self.territory_table_model.table_data[table_data_item.row()][-1]
        assert isinstance(territory_id, int)
        self.selected_territory_id_set = set([territory_id])
        self.update_gathering_item_filter()
        # self.item_table_proxy_model.set_territory_filter(self.selected_territory_id_set)
        # if table_view_item in self.territory_table_view.selectedIndexes():
        #     self.item_table_proxy_model.add_territory_filter(territory_id)
        # else:
        #     self.item_table_proxy_model.remove_territory_filter(territory_id)
        self.update_map_signal.emit(territory_id)

    @Slot(dict)
    def on_territory_to_gathering_item_dict_changed(
        self, territory_to_gathering_item_dict: Dict[int, Set[int]]
    ) -> None:
        if self.territory_to_gathering_item_dict != territory_to_gathering_item_dict:
            self.territory_to_gathering_item_dict = territory_to_gathering_item_dict
            self.update_gathering_item_filter()

    @Slot(dict)
    def on_gathering_item_to_territory_dict_changed(
        self, gathering_item_to_territory_dict: Dict[int, Set[int]]
    ) -> None:
        if self.gathering_item_to_territory_dict != gathering_item_to_territory_dict:
            self.gathering_item_to_territory_dict = gathering_item_to_territory_dict
            self.update_territory_filter()

    def update_territory_filter(self) -> None:
        territory_id_filter_set: Set[int] = set()
        for gathering_item_id in self.selected_gathering_item_id_set:
            territory_id_filter_set.update(
                self.gathering_item_to_territory_dict[gathering_item_id]
            )
        if self.territory_id_filter_set != territory_id_filter_set:
            territory_to_deselect = (
                self.selected_territory_id_set - self.territory_id_filter_set
            )
            self.territory_id_filter_set = territory_id_filter_set
            self.territory_table_proxy_model.set_territory_id_filter(
                territory_id_filter_set
            )
            if len(territory_to_deselect) > 0:
                print(
                    f"Deselecting territories {self.selected_territory_id_set - territory_to_deselect}"
                )
                self.selected_territory_id_set -= territory_to_deselect
                self.update_gathering_item_filter()

    def update_gathering_item_filter(self) -> None:
        gathering_item_id_filter_set: Set[int] = set()
        for territory_id in self.selected_territory_id_set:
            gathering_item_id_filter_set.update(
                self.territory_to_gathering_item_dict[territory_id]
            )
        if self.gathering_item_id_filter_set != gathering_item_id_filter_set:
            gathering_items_to_deselect = (
                self.selected_gathering_item_id_set - gathering_item_id_filter_set
            )
            self.gathering_item_id_filter_set = gathering_item_id_filter_set
            self.item_table_proxy_model.set_gathering_id_filter(
                gathering_item_id_filter_set
            )
            if len(gathering_items_to_deselect) > 0:
                # TODO: Maybe this should be a call to the gatthering_items table?
                print(
                    f"Deselecting items {self.selected_gathering_item_id_set - gathering_items_to_deselect}"
                )
                self.selected_gathering_item_id_set -= gathering_items_to_deselect
                self.update_territory_filter()

    # @Slot(QItemSelection, QItemSelection)
    # def on_gathering_item_selection_changed(
    #     self,
    #     selected: QItemSelection,
    #     deselected: QItemSelection,
    # ) -> None:
    #     selected_gathering_item_id_set: Set[int] = set()
    #     for row in set(
    #         selected_row.row()
    #         for selected_row in self.item_table_view.selectionModel().selectedRows()
    #     ):
    #         gathering_item_id = self.item_table_model.table_data[row][-1]
    #         assert isinstance(gathering_item_id, int)
    #         selected_gathering_item_id_set.add(gathering_item_id)
    #     print(f"Selected gathering items: {selected_gathering_item_id_set}")
    #     self.item_selection_changed_signal.emit(selected_gathering_item_id_set)

    # @Slot(QItemSelection, QItemSelection)
    # def on_territory_selection_changed(
    #     self, selected: QItemSelection, deselected: QItemSelection
    # ) -> None:
    #     selected_territory_id_set: Set[int] = set()
    #     for row in set(
    #         selected_row.row()
    #         for selected_row in self.territory_table_view.selectionModel().selectedRows()
    #     ):
    #         territory_id = self.territory_table_model.table_data[row][-1]
    #         assert isinstance(territory_id, int)
    #         selected_territory_id_set.add(territory_id)
    #     print(f"Selected territories: {selected_territory_id_set}")
    #     self.territory_selection_changed_signal.emit(selected_territory_id_set)

    def closeEvent(self, event) -> None:
        print("exiting Gatherer...")
        self.gatherer_worker.stop()
        self.gatherer_worker.wait()
        self.classjob_config_dict.save_to_disk()
        super().closeEvent(event)
