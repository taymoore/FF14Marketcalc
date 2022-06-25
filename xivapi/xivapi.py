from functools import partial
import logging
from typing import (
    Any,
    Callable,
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
import json, atexit
from pydantic import BaseModel
from pydantic_collections import BaseCollectionModel
from PySide6.QtCore import QMutex, QMutexLocker
from xivapi.models import (
    ClassJob,
    ClassJobCollection,
    Item,
    Page,
    PageResult,
    Recipe,
    RecipeCollection,
)
from cache import Persist, PersistMapping

_logger = logging.getLogger(__name__)

GET_CONTENT_RATE = 0.05
get_content_time = time.time() - GET_CONTENT_RATE

xivapi_mutex = QMutex()

R = TypeVar("R", bound=BaseModel)


def get_content(content_name: str, t: R):
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
            print(str(e))
        else:
            break
    xivapi_mutex.unlock()
    if content_response is not None:
        return t.parse_obj(content_response.json())
    else:
        raise RuntimeError("Failed to get content")


def _get_item(item_id: int) -> Item:
    return get_content(f"Item/{item_id}", Item)


get_item = Persist(_get_item, "items.json", 3600 * 24 * 30, Item)


def _get_classjob_doh_list() -> List[ClassJob]:
    classjob_doh_list = []
    for result_list in get_content_pages("ClassJob"):
        for result in result_list:
            classjob_info: ClassJob = get_content(result.Url, ClassJob)
            if classjob_info.ClassJobCategory.Name == "Disciple of the Hand":
                classjob_doh_list.append(classjob_info)
    return classjob_doh_list


get_classjob_doh_list = Persist(
    _get_classjob_doh_list, "classjob_doh.json", 3600 * 24 * 30, ClassJobCollection
)


def get_content_pages(content_name: str) -> Generator[List[PageResult], None, None]:
    first_page: Page = get_content(content_name, Page)
    yield first_page.Results
    for page in range(2, first_page.Pagination.PageTotal + 1):
        next_page: Page = get_content(f"{content_name}&page={page}", Page)
        yield next_page.Results


def _get_recipe(url: str) -> Recipe:
    return get_content(url, Recipe)


get_recipe = Persist(_get_recipe, "recipes.json", 3600 * 24 * 30, Recipe)


def get_recipe_by_id(recipe_id: int) -> Recipe:
    return get_recipe(f"Recipe/{recipe_id}")


def _get_recipes(classjob_id: int, classjob_level: int) -> RecipeCollection:
    recipe_collection = RecipeCollection()
    for recipe_results in get_content_pages(
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
    recipe_classjob_level_list_mutex.lock()
    if (
        classjob_id in recipe_classjob_level_list
        and classjob_level in recipe_classjob_level_list[classjob_id]
    ):
        print(f"Using cached recipes for {classjob_id} {classjob_level}")
        url_list = recipe_classjob_level_list[classjob_id][classjob_level]
        print(f"{len(url_list)} recipes")
        recipe_classjob_level_list_mutex.unlock()
        for url in url_list:
            yield get_recipe(url)
    else:
        print(f"No cached recipes for {classjob_id} {classjob_level}")
        recipe_classjob_level_list_mutex.unlock()
        url_list: List[str] = []
        for page_result_list in get_content_pages(
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
    for results in get_content_pages(f"search?string={search_string}"):
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
