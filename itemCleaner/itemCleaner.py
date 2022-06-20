import json
from typing import Callable, Dict, List
from PySide6.QtCore import Slot, Signal, QSize, QThread, QSemaphore, Qt, QBasicTimer
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
    QHeaderView,
    QAbstractItemView,
)
from pydantic import BaseModel
from universalis.universalis import get_listings, universalis_mutex

from xivapi.xivapi import get_item

# axis -> updateAutoSIPrefix can be disabled


class InventoryItemDescriptor(BaseModel):
    id: int
    amount: int


class ItemCleanerForm(QDialog):
    class ItemCleanerTable(QTableWidget):
        def __init__(self, parent: QWidget):
            super().__init__(parent)
            self.setColumnCount(4)
            self.setHorizontalHeaderLabels(
                ["Item", "Crafting Value", "Market Score", "Market Price"]
            )
            self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
            self.verticalHeader().hide()
            self.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.setMinimumSize(QSize(500, 1000))
            self.table_data: Dict[int, List[QTableWidgetItem]] = {}

        def clear_contents(self) -> None:
            self.clearContents()
            self.setRowCount(0)
            self.table_data.clear()

        def add_row(self, item_id: int, name: str, crafting_value: float):
            row_widgets: List[QTableWidgetItem] = []
            row_widgets.append(QTableWidgetItem(name))
            # Sort numerically: https://stackoverflow.com/questions/25533140/sorting-qtablewidget-items-numerically
            row_widgets.append(QTableWidgetItem(f"{crafting_value:.1f}"))
            universalis_mutex.lock()
            listings = get_listings(item_id, 55)
            universalis_mutex.unlock()
            row_widgets.append(
                QTableWidgetItem(
                    f"{listings.minPrice - listings.history['Price'].mean():.1f}"
                )
            )
            row_widgets.append(QTableWidgetItem(f"{listings.minPrice:.0f}"))
            self.insertRow(self.rowCount())
            self.setItem(self.rowCount() - 1, 0, row_widgets[0])
            self.setItem(self.rowCount() - 1, 1, row_widgets[1])
            self.setItem(self.rowCount() - 1, 2, row_widgets[2])
            self.setItem(self.rowCount() - 1, 3, row_widgets[3])
            self.table_data[item_id] = row_widgets

        def update_row(
            self,
            item_id: int,
            crafting_value: float,
        ):
            self.table_data[item_id][1].setText(f"{crafting_value:.1f}")

        def sort(self):
            # self.sortItems(0, Qt.DescendingOrder)
            self.sortItems(1)

    def __init__(self, parent, get_item_crafting_value_table: Callable):
        self.get_item_crafting_value_table = get_item_crafting_value_table
        super(ItemCleanerForm, self).__init__(parent)
        self.search_lineedit = QLineEdit(self)
        self.table = ItemCleanerForm.ItemCleanerTable(self)
        layout = QVBoxLayout()
        layout.addWidget(self.search_lineedit)
        layout.addWidget(self.table)
        self.search_lineedit.textChanged.connect(self.on_search_text_changed)
        self.search_lineedit.returnPressed.connect(self.on_search_return_pressed)
        self.setLayout(layout)

    @Slot()
    def on_search_return_pressed(self) -> None:
        self.on_search_text_changed(self.search_lineedit.text())

    @Slot()
    def on_search_text_changed(self, text) -> None:
        try:
            item_list: List[InventoryItemDescriptor] = [
                InventoryItemDescriptor.parse_obj(item) for item in json.loads(text)
            ]
            self.table.clear_contents()
            item_crafting_value_table = self.get_item_crafting_value_table()
            for item in item_list:
                if item.id in item_crafting_value_table.keys():
                    self.table.add_row(
                        item.id,
                        get_item(item.id).Name,
                        item_crafting_value_table[item.id],
                    )
            self.table.sort()
        except:
            print("Failed to load input")

    # # Greets the user
    # def greetings(self):
    #     print(f"Hello {self.edit.text()}")
