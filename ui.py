from typing import List, Tuple
import pyperclip
from PySide6.QtCore import Slot, Signal, QSize, QThread
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QHBoxLayout,
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
from universalis.universalis import get_listings
from xivapi.models import Recipe, RecipeCollection
from xivapi.xivapi import get_classjob_doh_list, search_recipes

world = 55


class MainWindow(QMainWindow):
    class TableView(QTableWidget):
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

        def add_recipes(self, recipes: RecipeCollection):
            recipe: Recipe
            row_data: List[Tuple[str, str, float, float, Recipe]] = []  # class, item_name, profit, velocity, recipe
            for recipe in recipes:
                row_data.append(
                    (
                        recipe.ClassJob.Abbreviation,
                        recipe.ItemResult.Name,
                        get_profit(recipe, world),
                        get_listings(recipe.ItemResult.ID, world).regularSaleVelocity,
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

    def __init__(self):
        super().__init__()

        self.refreshing_table = True

        self.main_layout = QVBoxLayout()

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
        self.main_layout.addLayout(self.search_layout)

        self.table = MainWindow.TableView(self)
        self.table.cellDoubleClicked.connect(self.on_table_double_clicked)
        self.main_layout.addWidget(self.table)

        self.recipe_textedit = QTextEdit(self)
        self.main_layout.addWidget(self.recipe_textedit)

        self.layout_widget = QWidget()
        self.layout_widget.setLayout(self.main_layout)
        self.setCentralWidget(self.layout_widget)

        self.status_bar_label = QLabel()
        self.statusBar().addPermanentWidget(self.status_bar_label, 1)

        self.setMinimumSize(QSize(400, 600))

        # classjob_list = get_classjob_doh_list()

        # https://realpython.com/python-pyqt-qthread/
        self.worker_thread = QThread(self)
        self.worker = Worker(
            classjob_level_max_dict={
                8: 69,
                9: 68,
                10: 67,
                11: 71,
                12: 67,
                13: 69,
                14: 68,
                15: 61,
            },
            world=world,
        )
        self.worker_queue_recipe_list: List[Recipe] = []    # Respective mutex is self.queue_worker_task
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker.status_bar_update_signal.connect(self.status_bar_label.setText)
        self.worker.table_refresh_signal.connect(self.on_worker_update)
        self.worker_thread.start()

    @Slot()
    def on_search_return_pressed(self):
        self.refreshing_table = False
        self.worker.xivapi_mutex.lock()
        recipes = search_recipes(self.search_qlineedit.text())
        self.worker.xivapi_mutex.unlock()
        self.table.clear_contents()
        self.worker.universalis_mutex.lock()
        self.table.add_recipes(recipes)
        self.worker.universalis_mutex.unlock()

    @Slot(int, int)
    def on_table_double_clicked(self, row: int, column: int):
        pyperclip.copy(self.table.recipe_list[row].ItemResult.Name)
        self.worker.universalis_mutex.lock()
        self.recipe_textedit.setText(print_recipe(self.table.recipe_list[row], world))
        self.worker.universalis_mutex.unlock()

    @Slot()
    def on_refresh_button_clicked(self):
        self.refreshing_table = True
        self.refresh_table()

    @Slot()
    def on_worker_update(self):
        self.refresh_table()

    def refresh_table(self):
        self.table.clear_contents()
        processed_recipes = self.worker._processed_recipe_list
        self.worker.universalis_mutex.lock()
        # TODO: Make this non-blocking
        self.table.add_recipes(processed_recipes)
        self.worker.universalis_mutex.unlock()

    def closeEvent(self, event):
        self.worker.stop()
        self.status_bar_label.setText("Exiting...")
        self.worker_thread.quit()
        self.worker_thread.wait()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication([])

    main_window = MainWindow()
    main_window.show()

    app.exec()
