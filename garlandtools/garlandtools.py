from collections import deque
from typing import (
    Any,
    Callable,
    Deque,
    Dict,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
    Generator,
)
import requests
import time
from pydantic import BaseModel, ValidationError
from pydantic_collections import BaseCollectionModel
from PySide6.QtCore import QMutex, QMutexLocker, QUrl, QTimer, QObject, QTimerEvent, Slot, Signal
from PySide6.QtNetwork import QNetworkRequest, QNetworkAccessManager, QNetworkReply
from cache import Persist, PersistMapping
from garlandtools.models import Item

class GarlandtoolsManager(QObject):
    item_received = Signal(Item)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._get_content_rate = 0.05
        self._get_content_time = time.time() - self._get_content_rate
        self._garlandtools_mutex = QMutex()
        self._network_access_manager = QNetworkAccessManager(self)
        self._network_access_manager.finished.connect(self._on_request_finished)
        self._url_request_queue: Deque[QUrl] = deque()
        self._request_timer = QTimer(self)
        self._request_timer.setSingleShot(True)
        self._active_request = None
        self.items = PersistMapping[int, Item]("garland_items.bin")

    def request_item(self, item_id: int) -> None:
        if item_id in self.items:
            self.item_received.emit(self.items[item_id])
        else:
            self.get_content(str(item_id))

    def get_content(self, content_name: str) -> None:
        print(f"Getting content: {content_name}")
        if content_name[0] == "/":
            content_name = content_name[1:]
        url = QUrl(f"https://www.garlandtools.org/db/doc/item/en/3/{content_name}.json")
        self._url_request_queue.append(url)
        if self._request_timer.isActive():
            return
        now_time = time.time()
        if now_time - self._get_content_time < self._get_content_rate:
            # Wait until 
            print(f"sleeping for {self._get_content_rate - now_time + self._get_content_time}s")
            self._request_timer.start((self._get_content_rate - now_time + self._get_content_time) * 1000)
        else:
            self._process_request_queue()

    def timerEvent(self, event: QTimerEvent) -> None:
        print("timer handler")
        if event.timerId() == self._request_timer.timerId():
            print(f"Timer event")
            self._process_request_queue()
        else:
            super().timerEvent(event)

    # Send a request to garland tools
    def _process_request_queue(self) -> None:
        try:
            assert len(self._url_request_queue) > 0
            assert self._active_request is None
            assert not self._request_timer.isActive()
            print(f"Processing request {self._url_request_queue[0].toString()}")
            url = self._url_request_queue[0]
            request = QNetworkRequest(url)
            self._active_request = self._network_access_manager.get(request)
            self._get_content_time = time.time()
        except Exception as e:
            print(str(e))

    # Data received from garland tools
    @Slot(QNetworkReply)
    def _on_request_finished(self, reply: QNetworkReply) -> None:
        if reply.error() == QNetworkReply.OperationCanceledError:
            print(reply.errorString())
            self._active_request = None
            reply.deleteLater()
            return
        elif reply.error() != QNetworkReply.NoError:
            print(reply.errorString())
            self._active_request = None
            self._url_request_queue.append(self._url_request_queue.popleft())
            self._request_timer.start(self._get_content_rate * 1000, self)
            reply.deleteLater()
            return
        try:
            item = Item.parse_raw(reply.readAll().data())
        except ValidationError as e:
            print(str(e))
        else:
            self.items[item.item.id] = item
            self.item_received.emit(item)
        finally:
            self._active_request = None
            self._url_request_queue.popleft()
            if len(self._url_request_queue) > 0:
                self._request_timer.start(self._get_content_rate * 1000, self)
            reply.deleteLater()
        # self._process_item(item)

    # def _process_item(self, item: Item) -> None:

    def save_to_disk(self) -> None:
        self.items.save_to_disk()