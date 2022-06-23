from PySide6.QtCore import QMutex

# https://stackoverflow.com/questions/11666610/how-to-give-priority-to-privileged-thread-in-mutex-locking
class PriorityMutex:
    data_mutex = QMutex()
    high_priority_mutex = QMutex()
    low_priority_mutex = QMutex()

    def low_priority_lock(self):
        self.low_priority_lock