from typing import List, Tuple
import pyperclip
from PySide6.QtCore import Slot, Signal, QSize, QThread, QSemaphore, Qt
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
)
from ff14marketcalc import get_profit, print_recipe
from worker import Worker
from retainerWorker.retainerWorker import RetainerWorker
from universalis.universalis import get_listings
from xivapi.models import Recipe, RecipeCollection
from xivapi.xivapi import get_classjob_doh_list, search_recipes

world = 55


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

            self.recipe_list: List[Recipe] = []

        def clear_contents(self) -> None:
            self.clearContents()
            self.setRowCount(0)
            self.recipe_list.clear()
            print("clear recipe list")

        def add_recipes(
            self,
            row_data: List[Tuple[str, str, float, float, Recipe]] = [],
            recipe_list: List[Recipe] = [],
        ):
            # TODO: Pass this recipe_list to the worker
            if len(recipe_list) > 0:
                for recipe in recipe_list:
                    row_data.append(
                        (
                            recipe.ClassJob.Abbreviation,
                            recipe.ItemResult.Name,
                            get_profit(recipe, world),
                            get_listings(
                                recipe.ItemResult.ID, world
                            ).regularSaleVelocity,
                            recipe,
                        )
                    )
                row_data.sort(key=lambda row: row[2] * row[3], reverse=True)
            for row_index, row in enumerate(row_data):
                self.insertRow(self.rowCount())
                self.setItem(row_index, 0, QTableWidgetItem(row[0]))
                self.setItem(row_index, 1, QTableWidgetItem(row[1]))
                self.setItem(row_index, 2, QTableWidgetItem(f"{row[2]:,.0f}"))
                self.setItem(
                    row_index,
                    3,
                    QTableWidgetItem(f"{row[3]:.2f}"),
                )
                self.setItem(row_index, 4, QTableWidgetItem(f"{row[2] * row[3]:,.0f}"))
                self.recipe_list.append(row[4])

        queue_worker_task = Signal()

    class RetainerTable(QTableWidget):
        def __init__(self, *args):
            super().__init__(*args)
            self.setColumnCount(4)
            self.setHorizontalHeaderLabels(
                ["Retainer", "Item", "Listed Price", "Min Price"]
            )
            self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            self.verticalHeader().hide()

            self.setEditTriggers(QAbstractItemView.NoEditTriggers)

            self.table_data: List[
                int, str, str, int, int
            ] = []  # row, retainer, item, listed_price, min_price

        def clear_contents(self) -> None:
            self.clearContents()
            self.setRowCount(0)
            self.table_data.clear()

    def __init__(self):
        super().__init__()

        self.refreshing_table = True

        self.main_widget = QWidget()
        self.main_layout = QVBoxLayout()
        self.centre_splitter = QSplitter()
        self.left_splitter = QSplitter()
        self.left_splitter.setOrientation(Qt.Orientation.Vertical)
        self.table_search_layout = QVBoxLayout()
        self.table_search_layout.setContentsMargins(0, 0, 0, 0)
        self.table_search_widget = QWidget()

        self.search_layout = QHBoxLayout()
        self.search_label = QLabel(self)
        self.search_label.setText("Search:")
        self.search_layout.addWidget(self.search_label)
        self.search_qlineedit = QLineEdit(self)
        self.search_qlineedit.returnPressed.connect(self.on_search_return_pressed)
        self.search_layout.addWidget(self.search_qlineedit)
        self.search_refresh_button = QPushButton(self)
        self.search_refresh_button.setText("Refresh")
        self.search_refresh_button.clicked.connect(self.on_refresh_button_clicked)
        self.search_layout.addWidget(self.search_refresh_button)
        self.table_search_layout.addLayout(self.search_layout)

        self.table = MainWindow.RecipeListTable(self)
        self.table.cellDoubleClicked.connect(self.on_table_double_clicked)
        self.table_search_layout.addWidget(self.table)

        self.table_search_widget.setLayout(self.table_search_layout)
        self.left_splitter.addWidget(self.table_search_widget)

        self.recipe_textedit = QTextEdit(self)
        self.left_splitter.addWidget(self.recipe_textedit)

        self.centre_splitter.addWidget(self.left_splitter)
        self.retainer_table = MainWindow.RetainerTable(self)
        self.centre_splitter.addWidget(self.retainer_table)

        self.main_layout.addWidget(self.centre_splitter)
        self.main_widget.setLayout(self.main_layout)
        self.setCentralWidget(self.main_widget)

        self.status_bar_label = QLabel()
        self.statusBar().addPermanentWidget(self.status_bar_label, 1)

        self.setMinimumSize(QSize(600, 600))

        # classjob_list = get_classjob_doh_list()

        # https://realpython.com/python-pyqt-qthread/
        self.worker_thread = QThread(self)
        self.worker = Worker(
            classjob_level_max_dict={
                8: 69,
                9: 70,
                10: 68,
                11: 74,
                12: 67,
                13: 70,
                14: 68,
                15: 63,
            },
            world=world,
            seller_id="4d9521317c92e33772cd74a166c72b0207ab9edc5eaaed5a1edb52983b70b2c2",
        )
        self.worker_queue_recipe_list: List[
            Recipe
        ] = []  # Respective mutex is self.queue_worker_task
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker.status_bar_update_signal.connect(self.status_bar_label.setText)
        self.worker.table_refresh_signal.connect(self.on_worker_update)
        self.worker_thread.start()

        self.retainerworker_thread = QThread()
        self.retainerworker = RetainerWorker()
        self.retainerworker.moveToThread(self.retainerworker_thread)
        # self.retainerworker_thread.started.connect(self.retainerworker.run)
        self.retainerworker_thread.finished.connect(self.worker.deleteLater)
        self.retainerworker_thread.start()

    @Slot()
    def on_search_return_pressed(self):
        self.refreshing_table = False
        self.worker.xivapi_mutex.lock()
        recipes = search_recipes(self.search_qlineedit.text())
        self.worker.xivapi_mutex.unlock()
        self.table.clear_contents()
        self.worker.universalis_mutex.lock()
        self.table.add_recipes(recipe_list=recipes)
        self.worker.universalis_mutex.unlock()

    @Slot(int, int)
    def on_table_double_clicked(self, row: int, column: int):
        item_name = self.table.recipe_list[row].ItemResult.Name
        pyperclip.copy(item_name)
        self.status_bar_label.setText(f"Processing {item_name}...")
        self.worker.universalis_mutex.lock()
        self.recipe_textedit.setText(print_recipe(self.table.recipe_list[row], world))
        self.worker.universalis_mutex.unlock()

    @Slot()
    def on_refresh_button_clicked(self):
        self.refreshing_table = True
        self.worker.refresh_recipe_request_sem.release()

    @Slot()
    def on_worker_update(self):
        if self.refreshing_table:
            self.refresh_table()

    def refresh_table(self):
        self.table.clear_contents()
        self.worker.universalis_mutex.lock()
        self.table.add_recipes(self.worker.table_row_data)
        self.worker.universalis_mutex.unlock()

    def closeEvent(self, event):
        self.worker.stop()
        # self.retainerworker.stop()
        self.status_bar_label.setText("Exiting...")
        self.worker_thread.quit()
        self.worker_thread.wait()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication([])

    main_window = MainWindow()
    main_window.show()

    app.exec()
