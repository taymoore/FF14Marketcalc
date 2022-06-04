from typing import List, Tuple
from PySide6.QtCore import Slot, Signal, QSize
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
)
from ff14marketcalc import get_profit, print_recipe
from universalis.universalis import get_listings
from xivapi.models import Recipe, RecipeCollection
from xivapi.xivapi import get_classjob_doh_list, search_recipes

world = 55


class MainWidget(QMainWindow):
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

            self.recipe_list = []

        def clear_contents(self) -> None:
            self.clearContents()
            self.setRowCount(0)
            self.recipe_list.clear()

        def add_recipes(self, recipes: RecipeCollection):
            recipe: Recipe
            row_data: List[Tuple[str, str, float, float, Recipe]] = []
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

    def __init__(self):
        super().__init__()

        self.main_layout = QVBoxLayout()

        self.search_layout = QHBoxLayout()
        self.search_label = QLabel(self)
        self.search_label.setText("Search:")
        self.search_layout.addWidget(self.search_label)
        self.search_qlineedit = QLineEdit(self)
        self.search_qlineedit.returnPressed.connect(self.on_search_return_pressed)
        self.search_layout.addWidget(self.search_qlineedit)
        self.main_layout.addLayout(self.search_layout)

        self.table = MainWidget.TableView(self)
        self.table.cellDoubleClicked.connect(self.on_table_double_clicked)
        self.main_layout.addWidget(self.table)

        self.recipe_textedit = QTextEdit(self)
        self.main_layout.addWidget(self.recipe_textedit)

        self.layout_widget = QWidget()
        self.layout_widget.setLayout(self.main_layout)
        self.setCentralWidget(self.layout_widget)
        self.setMinimumSize(QSize(400, 600))

        # classjob_list = get_classjob_doh_list()

    @Slot()
    def on_search_return_pressed(self):
        recipes = search_recipes(self.search_qlineedit.text())
        self.table.clear_contents()
        self.table.add_recipes(recipes)

    @Slot(int, int)
    def on_table_double_clicked(self, row: int, column: int):
        self.recipe_textedit.setText(print_recipe(self.table.recipe_list[row], world))


if __name__ == "__main__":
    app = QApplication([])

    widget = MainWidget()
    widget.show()

    app.exec()
