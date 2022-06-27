import json
import logging
from scipy import stats
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np
import pyperclip
from PySide6.QtCore import Slot, Signal, QSize, QThread, QSemaphore, Qt, QBasicTimer
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
from gathererWorker.gathererWorker import GathererWindow
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
from xivapi.models import ClassJob, Recipe, RecipeCollection
from xivapi.xivapi import (
    get_classjob_doh_list,
    get_recipe_by_id,
    get_recipes,
    search_recipes,
)
from xivapi.xivapi import save_to_disk as xivapi_save_to_disk

_logger = logging.getLogger(__name__)
_logger.setLevel(logging.DEBUG)

world_id = 55


class MainWindow(QMainWindow):
    class RecipeListTable(QTableWidget):
        def __init__(self, *args):
            super().__init__(*args)
            self.setColumnCount(5)
            self.setHorizontalHeaderLabels(
                ["Job", "Item", "Profit", "Velocity", "Score"]
            )
            self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            self.verticalHeader().hide()
            self.setEditTriggers(QAbstractItemView.NoEditTriggers)

            # recipe_id -> row
            self.table_data: Dict[int, List[QTableWidgetItem]] = {}

        def clear_contents(self) -> None:
            self.clearContents()
            self.setRowCount(0)
            self.table_data.clear()

        def remove_rows_above_level(
            self, classjob_id: int, classjob_level: int
        ) -> None:
            keys_to_remove = []
            for recipe_id in self.table_data.keys():
                recipe = get_recipe_by_id(recipe_id)
                if (
                    recipe.ClassJob.ID == classjob_id
                    and recipe.RecipeLevelTable.ClassJobLevel > classjob_level
                ):
                    keys_to_remove.append(recipe_id)
            for key in keys_to_remove:
                self.removeRow(self.table_data[key][0].row())
                del self.table_data[key]

        @Slot(Recipe, float, float)
        def on_recipe_table_update(
            self, recipe: Recipe, profit: float, velocity: float
        ) -> None:
            if recipe.ID in self.table_data:
                row = self.table_data[recipe.ID]
                row[2].setText(f"{profit:,.0f}")
                row[3].setText(f"{velocity:.2f}")
                row[4].setText(f"{profit * velocity:,.0f}")
            else:
                row: List[QTableWidgetItem] = []
                row.append(QTableWidgetFloatItem(recipe.ClassJob.Abbreviation))
                row.append(QTableWidgetFloatItem(recipe.ItemResult.Name))
                row.append(QTableWidgetFloatItem(f"{profit:,.0f}"))
                row.append(QTableWidgetFloatItem(f"{velocity:.2f}"))
                row.append(QTableWidgetFloatItem(f"{profit * velocity:,.0f}"))
                self.insertRow(self.rowCount())
                self.setItem(self.rowCount() - 1, 0, row[0])
                self.setItem(self.rowCount() - 1, 1, row[1])
                self.setItem(self.rowCount() - 1, 2, row[2])
                self.setItem(self.rowCount() - 1, 3, row[3])
                self.setItem(self.rowCount() - 1, 4, row[4])
                self.table_data[recipe.ID] = row
            self.sortItems(4, Qt.DescendingOrder)

    class RetainerTable(QTableWidget):
        def __init__(self, parent: QWidget, seller_id: int):
            super().__init__(parent)
            self.setColumnCount(4)
            self.setHorizontalHeaderLabels(
                ["Retainer", "Item", "Listed Price", "Min Price"]
            )
            self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            self.verticalHeader().hide()
            self.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.seller_id = seller_id
            self.table_data: Dict[
                int, List[List[QTableWidgetItem]]
            ] = {}  # itemID -> row -> column
            self.good_color = QColor(0, 255, 0, 50)
            self.bad_color = QColor(255, 0, 0, 50)

        def clear_contents(self) -> None:
            self.clearContents()
            self.setRowCount(0)
            self.table_data.clear()

        def get_min_price(self, listings: Listings) -> float:
            return min(
                [
                    listing.pricePerUnit
                    for listing in listings.listings
                    if listing.sellerID != self.seller_id
                ]
            )

        @Slot(list)
        def on_listing_data_updated(self, listing_data: ListingData) -> None:
            row_list_index = 0
            row_list = self.table_data.setdefault(listing_data.item.ID, [])
            for listing in listing_data.listings.listings:
                if listing.sellerID == self.seller_id:
                    if row_list_index < len(row_list):
                        row_data = row_list[row_list_index]
                        row_data[2].setText(f"{listing.pricePerUnit:,.0f}")
                        row_data[3].setText(
                            f"{self.get_min_price(listing_data.listings):,.0f}"
                        )
                    else:
                        row_data = [
                            QTableWidgetItem(listing.retainerName),
                            QTableWidgetItem(listing_data.item.Name),
                            QTableWidgetItem(f"{listing.pricePerUnit:,.0f}"),
                            QTableWidgetItem(
                                f"{self.get_min_price(listing_data.listings):,.0f}"
                            ),
                        ]
                        row_count = self.rowCount()
                        self.insertRow(row_count)
                        for column_index, widget in enumerate(row_data):
                            self.setItem(row_count, column_index, widget)
                        row_list.append(row_data)
                    if listing.pricePerUnit <= listing_data.listings.minPrice:
                        color = self.good_color
                    else:
                        color = self.bad_color
                    for table_widget_item in row_data:
                        table_widget_item.setBackground(color)
                    row_list_index += 1

    class PriceGraph(PlotWidget):
        class FmtAxesItem(AxisItem):
            def __init__(
                self,
                orientation,
                pen=None,
                textPen=None,
                linkView=None,
                parent=None,
                maxTickLength=-5,
                showValues=True,
                text="",
                units="",
                unitPrefix="",
                **args,
            ):
                super().__init__(
                    orientation,
                    pen,
                    textPen,
                    linkView,
                    parent,
                    maxTickLength,
                    showValues,
                    text,
                    units,
                    unitPrefix,
                    **args,
                )

            def tickStrings(self, values, scale, spacing):
                return [f"{v:,.0f}" for v in values]

        def __init__(self, parent=None, background="default", plotItem=None, **kargs):
            kargs["axisItems"] = {
                "bottom": DateAxisItem(),
                "left": MainWindow.PriceGraph.FmtAxesItem(orientation="left"),
                "right": MainWindow.PriceGraph.FmtAxesItem(orientation="right"),
            }
            super().__init__(parent, background, plotItem, **kargs)

            self.p1 = self.plotItem
            self.p1.getAxis("left").setLabel("Velocity", color="#00ffff")
            self.p1_pen = mkPen(color="#00ff00", width=2)

            ## create a new ViewBox, link the right axis to its coordinate system
            self.p2 = ViewBox()
            self.p1.showAxis("right")
            self.p1.scene().addItem(self.p2)
            self.p1.getAxis("right").linkToView(self.p2)
            self.p2.setXLink(self.p1)
            self.p1.getAxis("right").setLabel("Purchases", color="#00ff00")
            # # self.p1.vb.setLogMode("y", True)
            # self.p2.setLogMode(self.p1.getAxis("right"), True)
            # self.p1.getAxis("right").setLogMode(False, True)
            # self.p1.getAxis("right").enableAutoSIPrefix(False)

            ## create third ViewBox.
            ## this time we need to create a new axis as well.
            self.p3 = ViewBox()
            self.ax3 = MainWindow.PriceGraph.FmtAxesItem(orientation="right")
            self.p1.layout.addItem(self.ax3, 2, 3)
            self.p1.scene().addItem(self.p3)
            self.ax3.linkToView(self.p3)
            self.p3.setXLink(self.p1)
            self.p3.setYLink(self.p2)
            self.ax3.setZValue(-10000)
            self.ax3.setLabel("Listings", color="#ff00ff")
            self.ax3.hide()
            self.ax3.setGrid(128)
            # self.ax3.setLogMode(False, True)
            # self.p3.setLogMode("y", True)
            # self.ax3.hideAxis()
            # self.ax3.setLogMode(False, True)
            # self.ax3.enableAutoSIPrefix(False)

            self.updateViews()
            self.p1.vb.sigResized.connect(self.updateViews)

        @Slot()
        def updateViews(self) -> None:
            self.p2.setGeometry(self.p1.vb.sceneBoundingRect())
            self.p3.setGeometry(self.p1.vb.sceneBoundingRect())
            self.p2.linkedViewChanged(self.p1.vb, self.p2.XAxis)
            self.p3.linkedViewChanged(self.p1.vb, self.p3.XAxis)

        def auto_range(self):
            self.p2.enableAutoRange(axis="y")
            self.p3.enableAutoRange(axis="y")
            self.p1.vb.updateAutoRange()
            self.p2.updateAutoRange()
            self.p3.updateAutoRange()

            bounds = [np.inf, -np.inf]
            for items in (
                self.p1.vb.addedItems,
                self.p2.addedItems,
                self.p3.addedItems,
            ):
                for item in items:
                    _bounds = item.dataBounds(0)
                    if _bounds[0] is None or _bounds[1] is None:
                        continue
                    bounds[0] = min(_bounds[0], bounds[0])
                    bounds[1] = max(_bounds[1], bounds[1])
            if bounds[0] != np.inf and bounds[1] != -np.inf:
                self.p1.vb.setRange(xRange=bounds)

            bounds = [np.inf, -np.inf]
            for items in (
                self.p2.addedItems,
                self.p3.addedItems,
            ):
                for item in items:
                    _bounds = item.dataBounds(1)
                    if _bounds[0] is None or _bounds[1] is None:
                        continue
                    bounds[0] = min(_bounds[0], bounds[0])
                    bounds[1] = max(_bounds[1], bounds[1])
            if bounds[0] != np.inf and bounds[1] != -np.inf:
                self.p2.setRange(yRange=bounds)

        def wheelEvent(self, ev, axis=None):
            super().wheelEvent(ev)
            for vb in (
                self.p1.vb,
                self.p2,
                self.p3,
            ):
                if axis in (0, 1):
                    mask = [False, False]
                    mask[axis] = vb.state["mouseEnabled"][axis]
                else:
                    mask = vb.state["mouseEnabled"][:]
                s = 1.02 ** (
                    (ev.angleDelta().y() - ev.angleDelta().x())
                    * vb.state["wheelScaleFactor"]
                )  # actual scaling factor
                s = [(None if m is False else s) for m in mask]
                center = Point(
                    functions.invertQTransform(vb.childGroup.transform()).map(
                        ev.position()
                    )
                )

                vb._resetTarget()
                vb.scaleBy(s, center)
                ev.accept()
                vb.sigRangeChangedManually.emit(mask)

    # class JobLevelWidget(QWidget):
    #     def __init__(self, parent: Optional[QWidget] = ..., f: Qt.WindowFlags = ...) -> None:
    #         super().__init__(parent, f)

    class ClassJobLevelLayout(QHBoxLayout):
        joblevel_value_changed = Signal(int, int)

        def __init__(self, parent: QWidget, classjob_config: ClassJobConfig) -> None:
            self.classjob = ClassJob(**classjob_config.dict())
            super().__init__()
            self.label = QLabel(parent)
            self.label.setText(classjob_config.Abbreviation)
            self.label.setAlignment(Qt.AlignRight)
            self.label.setAlignment(Qt.AlignCenter)
            self.addWidget(self.label)
            self.spinbox = QSpinBox(parent)
            self.spinbox.setMaximum(90)
            self.spinbox.setValue(classjob_config.level)
            self.addWidget(self.spinbox)

            self.spinbox.valueChanged.connect(self.on_spinbox_value_changed)

        def on_spinbox_value_changed(self, value: int) -> None:
            _logger.info(f"{self.classjob.Abbreviation} level changed to {value}")
            self.joblevel_value_changed.emit(self.classjob.ID, value)

    retainer_listings_changed = Signal(Listings)
    classjob_level_changed = Signal(int, int)
    auto_refresh_listings_changed = Signal(bool)
    search_recipes = Signal(str)

    def __init__(self):
        super().__init__()

        self.main_widget = QWidget()

        self.menu_bar = QMenuBar(self)
        self.setMenuBar(self.menu_bar)
        self.item_cleaner_action = QWidgetAction(self)
        self.item_cleaner_action.setText("Item Cleaner")
        self.menu_bar.addAction(self.item_cleaner_action)
        self.item_cleaner_action.triggered.connect(self.on_item_cleaner_menu_clicked)
        self.gatherer_action = QWidgetAction(self)
        self.gatherer_action.setText("Gatherer")
        self.menu_bar.addAction(self.gatherer_action)
        self.gatherer_action.triggered.connect(self.on_gatherer_menu_clicked)

        self.main_layout = QVBoxLayout()
        self.classjob_level_layout = QHBoxLayout()
        self.main_layout.addLayout(self.classjob_level_layout)
        self.centre_splitter = QSplitter()
        self.left_splitter = QSplitter()
        self.left_splitter.setOrientation(Qt.Orientation.Vertical)
        self.right_splitter = QSplitter()
        self.right_splitter.setOrientation(Qt.Orientation.Vertical)
        self.centre_splitter.addWidget(self.left_splitter)
        self.centre_splitter.addWidget(self.right_splitter)
        self.table_search_layout = QVBoxLayout()
        self.table_search_layout.setContentsMargins(0, 0, 0, 0)
        self.table_search_widget = QWidget()

        self.search_layout = QHBoxLayout()
        self.search_label = QLabel(self)
        self.search_label.setText("Search:")
        self.search_layout.addWidget(self.search_label)
        self.search_lineedit = QLineEdit(self)
        self.search_lineedit.returnPressed.connect(self.on_search_return_pressed)
        self.search_layout.addWidget(self.search_lineedit)
        self.search_refresh_button = QPushButton(self)
        self.search_refresh_button.setText("Refresh")
        self.search_refresh_button.clicked.connect(self.on_refresh_button_clicked)
        self.search_layout.addWidget(self.search_refresh_button)
        self.table_search_layout.addLayout(self.search_layout)

        self.table = MainWindow.RecipeListTable(self)
        self.table.cellDoubleClicked.connect(self.on_table_double_clicked)
        self.table.cellClicked.connect(self.on_table_clicked)
        self.table_search_layout.addWidget(self.table)

        self.table_search_widget.setLayout(self.table_search_layout)
        self.left_splitter.addWidget(self.table_search_widget)

        self.recipe_textedit = QTextEdit(self)
        self.left_splitter.addWidget(self.recipe_textedit)

        self.seller_id = (
            "4d9521317c92e33772cd74a166c72b0207ab9edc5eaaed5a1edb52983b70b2c2"
        )
        set_seller_id(self.seller_id)

        self.retainer_table = MainWindow.RetainerTable(self, self.seller_id)
        self.retainer_table.cellClicked.connect(self.on_retainer_table_clicked)
        self.right_splitter.addWidget(self.retainer_table)

        self.price_graph = MainWindow.PriceGraph(self)
        # self.price_graph = MainWindow.PriceGraph()
        self.right_splitter.addWidget(self.price_graph)
        self.right_splitter.setSizes([1, 1])

        self.main_layout.addWidget(self.centre_splitter)
        self.main_widget.setLayout(self.main_layout)
        self.setCentralWidget(self.main_widget)

        self.status_bar_label = QLabel()
        self.statusBar().addPermanentWidget(self.status_bar_label, 1)

        self.setMinimumSize(QSize(1000, 600))

        # Classjob level stuff!
        _logger.info("Getting classjob list...")
        classjob_list: List[ClassJob] = get_classjob_doh_list()
        self.classjob_config = PersistMapping[int, ClassJobConfig](
            "classjob_config.bin",
            {
                classjob.ID: ClassJobConfig(**classjob.dict(), level=0)
                for classjob in classjob_list
            },
        )
        self.classjob_level_layout_list = []
        for classjob_config in self.classjob_config.values():
            self.classjob_level_layout_list.append(
                _classjob_level_layout := MainWindow.ClassJobLevelLayout(
                    self, classjob_config
                )
            )
            self.classjob_level_layout.addLayout(_classjob_level_layout)
            _classjob_level_layout.joblevel_value_changed.connect(
                self.on_classjob_level_value_changed
            )

        # https://realpython.com/python-pyqt-qthread/
        self.crafting_worker = CraftingWorker(
            world_id=world_id,
            classjob_config_dict=self.classjob_config,
            # classjob_level_max_dict={
            #     8: 71,
            #     9: 72,
            #     10: 69,
            #     11: 79,
            #     12: 71,
            #     13: 74,
            #     14: 71,
            #     15: 69,
            # },
        )
        self.crafting_worker.status_bar_update_signal.connect(
            self.status_bar_label.setText
        )
        self.crafting_worker.recipe_table_update_signal.connect(
            self.table.on_recipe_table_update
        )
        self.classjob_level_changed.connect(self.crafting_worker.set_classjob_level)
        self.auto_refresh_listings_changed.connect(
            self.crafting_worker.on_set_auto_refresh_listings
        )
        self.search_recipes.connect(self.crafting_worker.on_search_recipe)

        self.retainerworker_thread = QThread()
        self.retainerworker = RetainerWorker(
            seller_id=self.seller_id, world_id=world_id
        )
        self.retainerworker.moveToThread(self.retainerworker_thread)
        # self.retainerworker_thread.started.connect(self.retainerworker.run)
        self.retainerworker_thread.finished.connect(self.retainerworker.deleteLater)

        self.crafting_worker.seller_listings_matched_signal.connect(
            self.retainerworker.on_retainer_listings_changed
        )
        self.retainerworker.listing_data_updated.connect(
            self.retainer_table.on_listing_data_updated
        )

        self.crafting_worker.start(QThread.LowPriority)
        self.retainerworker.load_cache(
            self.crafting_worker.seller_listings_matched_signal
        )
        self.retainerworker_thread.start(QThread.LowPriority)

    @Slot(int, int)
    def on_classjob_level_value_changed(
        self, classjob_id: int, classjob_level: int
    ) -> None:
        # print(f"ui: Classjob {classjob_id} level changed to {classjob_level}")
        classjob_config = self.classjob_config[classjob_id]
        classjob_config.level = classjob_level
        self.classjob_config[classjob_id] = classjob_config
        self.table.remove_rows_above_level(classjob_id, classjob_level)
        self.classjob_level_changed.emit(classjob_id, classjob_level)
        _logger.info(f"updated {classjob_id} with {classjob_level}")

    @Slot()
    def on_item_cleaner_menu_clicked(self) -> None:
        form = ItemCleanerForm(self, self.crafting_worker.get_item_crafting_value_table)
        # TODO: Connect this
        # self.crafting_worker.crafting_value_table_changed.connect(self.form.on_crafting_value_table_changed)
        form.show()

    @Slot()
    def on_gatherer_menu_clicked(self) -> None:
        form = GathererWindow(world_id, self)
        form.show()

    @Slot()
    def on_search_return_pressed(self):
        self.table.clear_contents()
        self.search_recipes.emit(self.search_lineedit.text())

    @Slot(int, int)
    def on_retainer_table_clicked(self, row: int, column: int):
        for row_group_list in self.retainer_table.table_data.values():
            for widget_list in row_group_list:
                if widget_list[0].row() != row:
                    continue
                pyperclip.copy(widget_list[1].text())
                return

    @Slot(int, int)
    def on_table_clicked(self, row: int, column: int):
        for recipe_id, row_widget_list in self.table.table_data.items():
            if row_widget_list[0].row() == row:
                break
        pyperclip.copy(row_widget_list[1].text())
        self.plot_listings(
            get_listings(get_recipe_by_id(recipe_id).ItemResult.ID, world_id)
        )

    @Slot(int, int)
    def on_table_double_clicked(self, row: int, column: int):
        for recipe_id, row_widget_list in self.table.table_data.items():
            if row_widget_list[0].row() == row:
                break
        item_name = row_widget_list[1].text()
        self.status_bar_label.setText(f"Processing {item_name}...")
        self.recipe_textedit.setText(
            print_recipe(get_recipe_by_id(recipe_id), world_id)
        )

    def plot_listings(self, listings: Listings) -> None:
        self.price_graph.p1.clear()
        self.price_graph.p2.clear()
        self.price_graph.p3.clear()
        listings.history.sort_index(inplace=True)
        listings.listing_history.sort_index(inplace=True)
        self.price_graph.p1.plot(
            x=np.asarray(listings.history.index[1:]),
            y=(3600 * 24 * 7)
            / np.asarray(
                pd.Series(listings.history.index)
                - pd.Series(listings.history.index).shift(periods=1)
            )[1:],
            pen="c",
            symbol="o",
            symbolSize=5,
            symbolBrush=("c"),
        )

        if len(listings.history.index) > 2:
            # smoothing: https://stackoverflow.com/a/63511354/7552308
            # history_df = listings.history[["Price"]].apply(
            #     savgol_filter, window_length=5, polyorder=2
            # )
            # self.price_graph.p2.addItem(
            #     p2 := PlotDataItem(
            #         np.asarray(history_df.index),
            #         history_df["Price"].values,
            #         pen=self.price_graph.p1_pen,
            #         symbol="o",
            #         symbolSize=5,
            #         symbolBrush=("g"),
            #     ),
            # )
            self.price_graph.p2.addItem(
                p2 := PlotDataItem(
                    np.asarray(listings.history.index),
                    listings.history["Price"].values,
                    pen=self.price_graph.p1_pen,
                    symbol="o",
                    symbolSize=5,
                    symbolBrush=("g"),
                ),
            )

        if (
            listings.listing_history.index.size > 2
            and listings.listing_history["Price"].max()
            - listings.listing_history["Price"].min()
            > 0
        ):
            listing_history_df = listings.listing_history[
                (np.abs(stats.zscore(listings.listing_history)) < 3).all(axis=1)
            ]
            if listing_history_df.index.size != listings.listing_history.index.size:
                _logger.info("Ignoring outliers:")
                _logger.info(
                    listings.listing_history.loc[
                        listings.listing_history.index.difference(
                            listing_history_df.index
                        )
                    ]["Price"]
                )
        else:
            listing_history_df = listings.listing_history
        self.price_graph.p3.addItem(
            p3 := PlotDataItem(
                np.asarray(listing_history_df.index),
                listing_history_df["Price"].values,
                pen="m",
                symbol="o",
                symbolSize=5,
                symbolBrush=("m"),
            ),
        )
        # p3.setLogMode(False, True)
        self.price_graph.auto_range()

    @Slot()
    def on_refresh_button_clicked(self):
        self.search_lineedit.clear()
        self.table.clear_contents()
        self.auto_refresh_listings_changed.emit(True)

    def closeEvent(self, event):
        print("exiting ui...")
        self.crafting_worker.stop()
        self.crafting_worker.wait()
        self.retainerworker_thread.quit()
        self.retainerworker_thread.wait()
        self.classjob_config.save_to_disk()
        universalis_save_to_disk()
        xivapi_save_to_disk()
        self.retainerworker.save_cache()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication([])

    main_window = MainWindow()
    main_window.show()

    app.exec()

# Ideas:
# Better caching of persistent data
# look for matching retainers when pulling all data, not just in a few loops
