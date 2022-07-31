from enum import Enum, IntEnum, auto
from functools import partial
from collections import defaultdict, deque, namedtuple
from heapq import heappop, heappush
import logging
import re
import traceback
from typing import (
    Any,
    Callable,
    DefaultDict,
    Deque,
    Dict,
    Iterator,
    List,
    NamedTuple,
    Optional,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
    Generator,
)
import requests
import time
import json, atexit
from autoslot import Slots
from pydantic import BaseModel, ValidationError
from pydantic_collections import BaseCollectionModel
from PySide6.QtCore import (
    QMutex,
    QMutexLocker,
    QUrl,
    QTimer,
    QObject,
    QTimerEvent,
    Slot,
    Signal,
)
from PySide6.QtNetwork import QNetworkRequest, QNetworkAccessManager, QNetworkReply
from xivapi.models import (
    ClassJob,
    ClassJobCollection,
    Item,
    Page,
    PageResult,
    Recipe,
    RecipeCollection,
)
from cache import Persist, PersistMapping, get_size

_logger = logging.getLogger(__name__)
# _logger.setLevel(logging.DEBUG)

GET_CONTENT_RATE = 0.05
get_content_time = time.time() - GET_CONTENT_RATE

PRINT_CACHE_SIZE = False

xivapi_mutex = QMutex()

R = TypeVar("R", bound=BaseModel)


# TODO: Move this to QNetworkRequest
# https://stackoverflow.com/a/59537535/
def get_content(content_name: str, t: Optional[R] = None):
    if content_name[0] == "/":
        content_name = content_name[1:]
    url = f"https://xivapi.com/{content_name}"
    global get_content_time
    xivapi_mutex.lock()
    now_time = time.time()
    if now_time - get_content_time < GET_CONTENT_RATE:
        time.sleep(GET_CONTENT_RATE - now_time + get_content_time)
    for _ in range(10):
        try:
            content_response = requests.get(url)
            get_content_time = time.time()
            content_response.raise_for_status()
        except Exception as e:
            time.sleep(0.05)
            print(str(e))
        else:
            break
    xivapi_mutex.unlock()
    if content_response is not None:
        try:
            if t is not None:
                return t.parse_obj(content_response.json())
            else:
                print(f"size of response: {len(content_response.content)}")
                return content_response.content
        except ValidationError as e:
            print(f"'{content_name}' failed validation: {e}")
            print(f"Content Response: {content_response.text}")
            raise e
    else:
        raise RuntimeError("Failed to get content")


def _get_item(item_id: int) -> Item:
    return get_content(f"Item/{item_id}", Item)


get_item = Persist(_get_item, "items.json", 3600 * 24 * 30, Item)

if PRINT_CACHE_SIZE:
    print(f"Size of item cache: {len(get_item.cache)} {get_size(get_item):,.0f} bytes")


def _get_classjob_doh_list() -> List[ClassJob]:
    classjob_doh_list = []
    for result_list in get_content_page_results("ClassJob"):
        for result in result_list:
            classjob_info: ClassJob = get_content(result.Url, ClassJob)
            if classjob_info.ClassJobCategory.Name == "Disciple of the Hand":
                classjob_doh_list.append(classjob_info)
    return classjob_doh_list


get_classjob_doh_list = Persist(
    _get_classjob_doh_list, "classjob_doh.json", 3600 * 24 * 30, ClassJobCollection
)

if PRINT_CACHE_SIZE:
    print(
        f"Size of classjob cache: {len(get_classjob_doh_list.cache)} {get_size(get_classjob_doh_list):,.0f} bytes"
    )


def get_content_page_results(
    content_name: str,
) -> Generator[List[PageResult], None, None]:
    first_page: Page = get_content(content_name, Page)
    yield first_page.Results
    for page in range(2, first_page.Pagination.PageTotal + 1):
        next_page: Page = get_content(
            f"{content_name}&page={page}", Page
        )  # TODO: This should use ? when not searching
        yield next_page.Results


# def yeild_content_page(content_name: str) -> Generator[Page, None, None]:
#     first_page: Page = get_content(content_name, Page, False)
#     yield first_page
#     for page in range(2, first_page.Pagination.PageTotal + 1):
#         yield get_page(content_name, page)


def get_page(content_name: str, page: int) -> Page:
    if "search" in content_name:
        delim = "&"
    else:
        delim = "?"
    return get_content(f"{content_name}{delim}page={page}", Page)


def _get_recipe(url: str) -> Recipe:
    return get_content(url, Recipe)


get_recipe = Persist(_get_recipe, "recipes.json", 3600 * 24 * 30, Recipe)

if PRINT_CACHE_SIZE:
    print(
        f"Size of recipe cache: {len(get_recipe.cache)} {get_size(get_recipe):,.0f} bytes"
    )


def get_recipe_by_id(recipe_id: int) -> Recipe:
    return get_recipe(f"/Recipe/{recipe_id}")


def _get_recipes(classjob_id: int, classjob_level: int) -> RecipeCollection:
    recipe_collection = RecipeCollection()
    for recipe_results in get_content_page_results(
        f"search?filters=RecipeLevelTable.ClassJobLevel={classjob_level},ClassJob.ID={classjob_id}"
    ):
        for recipe_result in recipe_results:
            recipe_collection.append(get_recipe(recipe_result.Url))
    return recipe_collection


get_recipes = Persist(
    _get_recipes, "recipe_collection.json", 3600 * 24 * 30, RecipeCollection
)

# Mapping classjob_id -> classjob_level -> list of recipe urls
recipe_classjob_level_list_mutex = QMutex()
recipe_classjob_level_list = PersistMapping[int, Dict[int, List[str]]](
    "classjob_level_list.bin"
)


def yield_recipes(
    classjob_id: int, classjob_level: int
) -> Generator[Recipe, None, None]:
    # print(f"yield_recipes: {classjob_id} {classjob_level}")
    recipe_classjob_level_list_mutex.lock()
    url_list: List[str]
    if (
        classjob_id in recipe_classjob_level_list
        and classjob_level in recipe_classjob_level_list[classjob_id]
    ):
        url_list = recipe_classjob_level_list[classjob_id][classjob_level]
        # print(f"{len(url_list)} recipes")
        recipe_classjob_level_list_mutex.unlock()
        for url in url_list:
            yield get_recipe(url)
    else:
        print(f"No cached recipes for {classjob_id} {classjob_level}")
        recipe_classjob_level_list_mutex.unlock()
        url_list = []
        for page_result_list in get_content_page_results(
            f"search?filters=RecipeLevelTable.ClassJobLevel={classjob_level},ClassJob.ID={classjob_id}"
        ):
            print(f"{len(page_result_list)} recipes")
            for page_result in page_result_list:
                if page_result.UrlType == "Recipe":
                    url_list.append(page_result.Url)
                    yield get_recipe(page_result.Url)
        recipe_classjob_level_list_mutex.lock()
        recipe_classjob_level_list.setdefault(classjob_id, {})[
            classjob_level
        ] = url_list
        recipe_classjob_level_list_mutex.unlock()


def get_recipes_up_to_level(
    classjob_id: int, classjob_level_max: int
) -> RecipeCollection:
    recipe_collection = RecipeCollection()
    for classjob_level in range(1, classjob_level_max + 1):
        _logger.log(
            logging.INFO, f"Searching class {classjob_id}, level {classjob_level}"
        )
        recipe_collection.extend(get_recipes(classjob_id, classjob_level))
    return recipe_collection


def search_recipes(search_string: str) -> RecipeCollection:
    recipe_collection = RecipeCollection()
    for results in get_content_page_results(f"search?string={search_string}"):
        for recipe_result in results:
            if recipe_result.UrlType == "Recipe":
                recipe_collection.append(get_recipe(recipe_result.Url))
    return recipe_collection


def save_to_disk() -> None:
    recipe_classjob_level_list.save_to_disk()
    get_item.save_to_disk()
    get_classjob_doh_list.save_to_disk()
    get_recipe.save_to_disk()
    get_recipes.save_to_disk()


class XivapiManager(QObject):
    recipe_received = Signal(Recipe)
    item_received = Signal(Item)
    status_bar_set_text_signal = Signal(str)

    class RequestType(IntEnum):
        ITEM = 0  # user requested item
        RECIPE_MANUAL = 1  # user requested recipe
        RECIPE_AUTO = 2  # background worker requested recipe
        RECIPE_INDEX = 3  # background worker requested page of recipes

    class RequestTuple(NamedTuple):
        type: "XivapiManager.RequestType"
        url: QUrl
        classjob_level: Optional[int] = None
        classjob_id: Optional[int] = None
        page: Optional[int] = None

    # Named method to allow pickling nested defaultdict
    def _create_defaultdict_set() -> DefaultDict[int, Set[int]]:
        return defaultdict(set)

    def __init__(self, world_id: int, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._world_id = world_id
        self._get_content_rate = 0.05
        self._get_content_time = time.time() - self._get_content_rate
        self._network_access_manager = QNetworkAccessManager(self)
        self._network_access_manager.finished.connect(self._on_request_finished)  # type: ignore
        self._request_queue: List[XivapiManager.RequestTuple] = []
        self._request_timer = QTimer(self)
        self._request_timer.setSingleShot(True)
        self._request_timer.timeout.connect(self._process_request_queue)  # type: ignore
        self._active_request: Optional[XivapiManager.RequestTuple] = None
        self._emitted_recipe_id_set: Set[int] = set()

        self._classjob_recipe_id_dict = PersistMapping[int, DefaultDict[int, Set[int]]](
            "recipe_index.bin",
            default=defaultdict(XivapiManager._create_defaultdict_set),
        )  # classjob_id -> classjob_level -> recipe_id
        self._classjob_recipe_page_dict = PersistMapping[int, Dict[int, int]](
            "recipe_page.bin", default=defaultdict(dict)
        )
        # self._classjob_id_level_max: Dict[int, int] = {}     # TODO: Remove redundant dict not used anywhere
        self._classjob_id_level_current: Dict[int, int] = {}

        self._recipes = PersistMapping[int, Recipe]("recipies.bin")
        self._recipes_mutex = QMutex()
        self.items = PersistMapping[int, Item]("items.bin")

    @property
    def recipies(self) -> PersistMapping[int, Recipe]:
        with QMutexLocker(self._recipes_mutex):
            return self._recipes

    @Slot(int, int)
    def set_classjob_id_level_max_slot(
        self, classjob_id: int, classjob_level_max: int
    ) -> None:
        _logger.debug(f"set_classjob_id_level_max: {classjob_id} {classjob_level_max}")
        # self._classjob_id_level_max[classjob_id] = classjob_level_max
        self._classjob_id_level_current[classjob_id] = classjob_level_max
        if (
            self._active_request is None
            or self._active_request.type != XivapiManager.RequestType.RECIPE_INDEX
        ) and not any(
            request.type == XivapiManager.RequestType.RECIPE_INDEX
            for request in self._request_queue
        ):
            self._request_recipe_index()

    @Slot(int, bool)
    def request_recipe(self, recipe_id: int, auto: bool = False) -> Optional[Recipe]:
        with QMutexLocker(self._recipes_mutex):
            if recipe_id in self._recipes:
                try:
                    if (
                        recipe_id not in self._emitted_recipe_id_set
                        and not self._recipes[recipe_id].ItemResult.IsUntradable
                    ):
                        self.recipe_received.emit(self._recipes[recipe_id])
                        self._emitted_recipe_id_set.add(recipe_id)
                    return self._recipes[recipe_id]
                except AttributeError as e:
                    _logger.error(f"Error getting recipe {recipe_id}")
                    _logger.error(
                        f"ItemResult: {self._recipes[recipe_id].ItemResult.dict()}"
                    )
                    raise e
        _logger.debug(f"request_recipe: {recipe_id}, auto: {auto}")
        url = QUrl(f"https://xivapi.com/Recipe/{recipe_id}")
        request = XivapiManager.RequestTuple(
            type=XivapiManager.RequestType.RECIPE_MANUAL
            if not auto
            else XivapiManager.RequestType.RECIPE_AUTO,
            url=url,
        )
        self._request_content(request)
        return None

    def _request_recipe_index(
        self,
        classjob_id: Optional[int] = None,
        classjob_level: Optional[int] = None,
        page: int = 1,
    ) -> None:
        """
        Requests a page of recipes.
        set classjob_id and classjob_level to None to request highest level recipes that have not been downloaded yet.
        """
        _logger.debug(f"_request_recipe_index: {classjob_id} {classjob_level} {page}")
        if classjob_id is None or classjob_level is None:
            assert classjob_id is None
            assert classjob_level is None
            assert page == 1
            try:
                assert not any(
                    request.type == XivapiManager.RequestType.RECIPE_INDEX
                    for request in self._request_queue
                )
            except AssertionError:
                raise RuntimeError(
                    f"Already requesting recipe index. {self._request_queue}"
                )
            # Find highest classjob level page that hasn't been downloaded
            while classjob_id is None:
                if all(
                    classjob_level <= 0
                    for classjob_level in self._classjob_id_level_current.values()
                ):
                    _logger.debug("No recipes to request")
                    return
                classjob_id = max(
                    self._classjob_id_level_current,
                    key=lambda key: self._classjob_id_level_current[key],
                )
                classjob_level = self._classjob_id_level_current[classjob_id]
                # If page is already downloaded
                if (
                    self._classjob_recipe_page_dict[classjob_id].get(classjob_level)
                    == -1
                ):
                    for recipe_id in self._classjob_recipe_id_dict[classjob_id][
                        classjob_level
                    ]:
                        # Emit or download the recipe
                        self.request_recipe(recipe_id, auto=True)
                    self._classjob_id_level_current[classjob_id] -= 1
                    classjob_id = None
            _logger.debug(
                f"Selected class {classjob_id} level {classjob_level} page {page}"
            )
        url = QUrl(
            f"https://xivapi.com/search?filters=RecipeLevelTable.ClassJobLevel={classjob_level},ClassJob.ID={classjob_id}&page={page}"
        )
        request = XivapiManager.RequestTuple(
            type=XivapiManager.RequestType.RECIPE_INDEX,
            url=url,
            classjob_level=classjob_level,
            classjob_id=classjob_id,
            page=page,
        )
        self._request_content(request)

    def _request_content(self, request: RequestTuple) -> None:
        heappush(self._request_queue, request)
        self._run()

    def _run(self) -> None:
        if (
            self._active_request is None
            and not self._request_timer.isActive()
            and len(self._request_queue) > 0
        ):
            now_time = time.time()
            if now_time - self._get_content_time < self._get_content_rate:
                _logger.debug(
                    f"sleeping for {self._get_content_rate - now_time + self._get_content_time}s"
                )
                self._request_timer.start(
                    int(
                        (self._get_content_rate - now_time + self._get_content_time)
                        * 1000
                    )
                )
            else:
                self._process_request_queue()

    # Send a request to xivapi
    @Slot()
    def _process_request_queue(self) -> None:
        if _logger.isEnabledFor(logging.DEBUG):
            _logger.debug(
                f"_process_request_queue: {[request.type.name for request in self._request_queue]}"
            )
        try:
            assert len(self._request_queue) > 0
            assert self._active_request is None
            assert not self._request_timer.isActive()
            self._active_request = heappop(self._request_queue)
            network_request = QNetworkRequest(self._active_request.url)
            xivapi_mutex.lock()  # eventually remove this
            self._network_access_manager.get(network_request)
            self._get_content_time = time.time()
            _logger.debug(
                f"Processing request {self._active_request.type.name} {self._active_request.url.toString()}"
            )
        except Exception as e:
            _logger.exception(e)

    # Data received
    @Slot(QNetworkReply)
    def _on_request_finished(self, reply: QNetworkReply) -> None:
        xivapi_mutex.unlock()  # eventually remove this
        try:
            assert self._active_request is not None
            if reply.error() != QNetworkReply.NoError:
                _logger.warning(reply.errorString())
                heappush(self._request_queue, self._active_request)
                self._active_request = None
                return
            try:
                assert self._active_request is not None
            except AssertionError:
                _logger.warning(
                    f"Received data with no active request. Data: {reply.readAll()}"
                )
                return
            if self._active_request.type == XivapiManager.RequestType.ITEM:
                self._on_item_request_finished(reply)
                self._active_request = None
            elif (
                self._active_request.type == XivapiManager.RequestType.RECIPE_AUTO
                or self._active_request.type == XivapiManager.RequestType.RECIPE_MANUAL
            ):
                self._on_recipe_request_finished(reply)
                self._active_request = None
            elif self._active_request.type == XivapiManager.RequestType.RECIPE_INDEX:
                self._on_recipe_index_request_finished(reply)
            else:
                raise Exception(f"Unknown request type {self._active_request.type}")
        finally:
            self._run()
            reply.deleteLater()

    def _on_item_request_finished(self, reply: QNetworkReply) -> None:
        try:
            item = Item.parse_raw(reply.readAll().data())
        except ValidationError as e:
            _logger.exception(e)
        else:
            _logger.debug(f"Received item {item.ID}")
            self.items[item.ID] = item
            self.item_received.emit(item)

    def _on_recipe_request_finished(self, reply: QNetworkReply) -> None:
        try:
            recipe = Recipe.parse_raw(reply.readAll().data())
        except ValidationError as e:
            _logger.exception(e)
        else:
            _logger.debug(f"Received recipe {recipe.ID}")
            with QMutexLocker(self._recipes_mutex):
                self._recipes[recipe.ID] = recipe
            self._emitted_recipe_id_set.add(recipe.ID)
            if not recipe.ItemResult.IsUntradable:
                self.recipe_received.emit(recipe)

    def _on_recipe_index_request_finished(self, reply: QNetworkReply) -> None:
        try:
            page = Page.parse_raw(reply.readAll().data())
        except ValidationError as e:
            _logger.exception(e)
        else:
            assert self._active_request is not None
            active_request = self._active_request
            self._active_request = None
            classjob_id = active_request.classjob_id
            assert classjob_id is not None
            classjob_level = active_request.classjob_level
            assert classjob_level is not None
            _logger.debug(
                f"Received recipe index classjob_id {classjob_id}, classjob_level {classjob_level}, page {page.Pagination.Page}"
            )
            # Request recipes
            for page_result in page.Results:
                if page_result.UrlType == "Recipe":
                    recipe_id = page_result.ID
                    self._classjob_recipe_id_dict[classjob_id][classjob_level].add(
                        recipe_id
                    )
                    self.request_recipe(recipe_id, True)
            # Request next page
            if page.Pagination.Page < page.Pagination.PageTotal:
                self._request_recipe_index(
                    classjob_id,
                    classjob_level,
                    page.Pagination.PageNext,
                )
                assert active_request.page is not None
                self._classjob_recipe_page_dict[classjob_id][
                    classjob_level
                ] = active_request.page
            else:
                self._classjob_recipe_page_dict[classjob_id][classjob_level] = -1
                self._request_recipe_index()

    @Slot()
    def save_to_disk(self) -> None:
        print("xivapi_manager.save_to_disk()")
        self._classjob_recipe_page_dict.save_to_disk()
        self._classjob_recipe_id_dict.save_to_disk()
        self._recipes.save_to_disk()
        self.items.save_to_disk()
