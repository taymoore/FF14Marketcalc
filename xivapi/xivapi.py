from functools import cache, partial
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
from xivapi.models import (
    ClassJob,
    ClassJobCollection,
    Item,
    Page,
    PageResult,
    Recipe,
    RecipeCollection,
)
from cache import persist_to_file

_logger = logging.getLogger(__name__)

GET_CONTENT_RATE = 0.05
get_content_time = time.time() - GET_CONTENT_RATE


R = TypeVar("R", bound=BaseModel)

# TODO: Paginate this
# https://stackoverflow.com/a/50259251/7552308
# TODO: Give this a return type
@cache
def get_content(content_name: str, t: R):
    _logger.log(logging.INFO, f"getting {content_name}")
    if content_name[0] == "/":
        content_name = content_name[1:]
    url = f"https://xivapi.com/{content_name}"
    global get_content_time
    now_time = time.time()
    if now_time - get_content_time < GET_CONTENT_RATE:
        # print(f"Sleeping for {GET_CONTENT_RATE - now_time + get_content_time}s")
        time.sleep(GET_CONTENT_RATE - now_time + get_content_time)
    content_response = requests.get(url)
    get_content_time = time.time()
    content_response.raise_for_status()
    return t.parse_obj(content_response.json())


@persist_to_file("items.json", 3600 * 24 * 30, Item)
def get_item(item_id: int) -> Item:
    return get_content(f"Item/{item_id}", Item)


@persist_to_file("classjob_doh.json", 3600 * 24 * 30, ClassJobCollection)
def get_classjob_doh_list() -> List[ClassJob]:
    classjob_doh_list = []
    for result_list in get_content_pages("ClassJob"):
        for result in result_list:
            classjob_info: ClassJob = get_content(result.Url, ClassJob)
            if classjob_info.ClassJobCategory.Name == "Disciple of the Hand":
                classjob_doh_list.append(classjob_info)
    return classjob_doh_list


def get_content_pages(content_name: str) -> Generator[List[PageResult], None, None]:
    first_page: Page = get_content(content_name, Page)
    yield first_page.Results
    for page in range(2, first_page.Pagination.PageTotal + 1):
        next_page: Page = get_content(f"{content_name}&page={page}", Page)
        yield next_page.Results


@persist_to_file("recipes.json", 3600 * 24 * 30, Recipe)
def get_recipe(url) -> Recipe:
    return get_content(url, Recipe)


@persist_to_file("recipe_collection.json", 3600 * 24 * 30, RecipeCollection)
def get_recipes(classjob_id: int, classjob_level: int) -> RecipeCollection:
    recipe_collection = RecipeCollection()
    for recipe_results in get_content_pages(
        f"search?filters=RecipeLevelTable.ClassJobLevel={classjob_level},ClassJob.ID={classjob_id}"
    ):
        for recipe_result in recipe_results:
            recipe_collection.append(get_recipe(recipe_result.Url))
    return recipe_collection


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
