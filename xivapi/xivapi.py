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
    Page,
    PageResult,
    ClassJobInfo,
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


@cache
def get_classjob_list() -> List[ClassJob]:
    page = Page.parse_obj(get_content("ClassJob"))
    return [ClassJob.parse_obj(result) for result in page.Results]
    # classjob_list = [ClassJob.parse_obj(result) for result in page.Results]
    # print([classjob.Name for classjob in classjob_list])


class ClassJobInfoCollection(BaseCollectionModel[ClassJobInfo]):
    class Config:
        validate_assignment_strict = False


@persist_to_file("classjob_doh.json", 3600 * 24 * 30, ClassJobInfoCollection)
def get_classjob_doh_list() -> List[ClassJobInfo]:
    classjob_doh_list = []
    for classjob in get_classjob_list():
        classjob_info = ClassJobInfo.parse_obj(get_content(classjob.Url))
        if classjob_info.ClassJobCategory.Name == "Disciple of the Hand":
            classjob_doh_list.append(classjob_info)
    return classjob_doh_list


def get_content_pages(content_name: str) -> Generator[List[PageResult], None, None]:
    first_page: Page = get_content(content_name, Page)
    yield first_page.Results
    for page in range(2, first_page.Pagination.PageTotal + 1):
        next_page: Page = get_content(f"{content_name}?page={page}", Page)
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


if __name__ == "__main__":
    recipes = get_recipes(classjob_id=8, classjob_level=67)
    print(recipes)
    # recipe: Recipe
    # for recipe in recipes:

    # # for page in get_content_pages("search?filters=RecipeLevelTable.ClassJobLevel=67"):
    # #     print(page)
    # # # for page in get_content_pages("item"):
    # # #     print(page)
    # # # x = get_content("Item/19927", Item)
    # # # print(x)
