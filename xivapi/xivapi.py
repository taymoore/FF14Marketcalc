from functools import cache, partial
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


GET_CONTENT_RATE = 0.05
get_content_time = time.time() - GET_CONTENT_RATE


def persist_to_file(file_name: str, timeout_s: float, return_type: BaseCollectionModel):

    try:
        cache: Dict[Any, Tuple[BaseModel, float]] = {
            param: (
                return_type.parse_raw(value[0]),
                value[1],
            )
            for param, value in json.load(open(f".data/{file_name}", "r")).items()
        }
    except (IOError, ValueError):
        print("Error loading cache")
        cache = {}

    def save_to_disk(
        cache: Dict[Any, Tuple[Any, float]], file_name: str, return_type: BaseModel
    ):
        new_cache: Dict[Any, Tuple[str, float]] = {
            param: (
                value[0].json()
                if isinstance(value[0], BaseModel)
                else return_type.parse_obj(value[0]).json(),
                value[1],
            )
            for param, value in cache.items()
        }
        json.dump(new_cache, open(f".data/{file_name}", "w"))

    atexit.register(partial(save_to_disk, cache, file_name, return_type))

    def decorator(func):
        def new_func(*args, **kwargs):
            if args is None:
                args = []
            else:
                args = list(args)
            if kwargs is not None:
                for kwarg_value in kwargs.values():
                    args.append(kwarg_value)

            if len(args) == 0:
                if len(cache) > 0:
                    print(f"Age of Cache: {time.time() - cache['null'][1]}s")
                if len(cache) == 0 or time.time() - cache["null"][1] > timeout_s:
                    cache["null"] = (func(), time.time())
                args = "null"
            else:
                if str(args) in cache:
                    print(f"Age of Cache: {time.time() - cache[str(args)][1]}s")
                if (
                    str(args) not in cache
                    or time.time() - cache[str(args)][1] > timeout_s
                ):
                    cache[str(args)] = (func(*args), time.time())

            return cache[str(args)][0]

        return new_func

    return decorator


R = TypeVar("R", bound=BaseModel)

# TODO: Paginate this
# https://stackoverflow.com/a/50259251/7552308
# TODO: Give this a return type
@cache
def get_content(content_name: str, t: R):
    print(f"getting {content_name}")
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
