from PySide6.QtWidgets import QTableWidgetItem


class QTableWidgetFloatItem(QTableWidgetItem):
    def __init__(self, text: str = None):
        super().__init__(text)

    def __lt__(self, other):
        if isinstance(other, QTableWidgetFloatItem):
            self_data_value = float(self.text().replace(",", ""))
            other_data_value = float(other.text().replace(",", ""))
            return self_data_value < other_data_value
        else:
            return QTableWidgetItem.__lt__(self, other)
