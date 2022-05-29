from email.generator import Generator
from functools import cache, partial
from typing import Any, Dict, List, Optional, Tuple, Type, Union
import requests
import time
import json, atexit
from pydantic import BaseModel
from pydantic_collections import BaseCollectionModel
from xivapi.models import ClassJob, Page, ClassJobInfo


GET_CONTENT_RATE = 0.05
get_content_time = time.time() - GET_CONTENT_RATE


def persist_to_file(file_name: str, timeout_s: float, return_type: BaseModel):

    try:
        cache = json.load(open(file_name, "r"))
        cache: Dict[Any, Tuple[BaseModel, float]] = {
            param: (
                return_type.parse_raw(value[0]),
                value[1],
            )
            for param, value in cache.items()
        }
    except (IOError, ValueError):
        print("Error loading cache")
        cache = {}

    def save_to_disk(
        cache: Dict[Any, Tuple[Any, float]], file_name: str, return_type: BaseModel
    ):
        cache: Dict[Any, Tuple[BaseModel, float]] = {
            param: (
                value[0].json()
                if isinstance(value[0], BaseModel)
                else return_type.parse_obj(value[0]).json(),
                value[1],
            )
            for param, value in cache.items()
        }
        json.dump(cache, open(file_name, "w"))

    atexit.register(partial(save_to_disk, cache, file_name, return_type))

    def decorator(func):
        def new_func(param: Optional[Any] = None):
            if param is None:
                if len(cache) > 0:
                    print(
                        f"Age of Cache: {time.time() - cache.get(0, cache.get('0'))[1]}s"
                    )
                if (
                    len(cache) == 0
                    or time.time() - cache.get(0, cache["0"])[1] > timeout_s
                ):
                    cache[0] = (func(), time.time())
                param = 0
            else:
                if param in cache:
                    print(f"Age of Cache: {time.time() - cache[param][1]}s")
                if param not in cache or time.time() - cache[param][1] > timeout_s:
                    cache[param] = (func(param), time.time())
            return cache.get(param, cache[str(param)])[0]

        return new_func

    return decorator


# TODO: Paginate this
# https://stackoverflow.com/a/50259251/7552308
@cache
def get_content(content_name: str) -> Dict:
    print(f"getting {content_name}")
    if content_name[0] == "/":
        content_name = content_name[1:]
    url = f"https://xivapi.com/{content_name}"
    global get_content_time
    now_time = time.time()
    if now_time - get_content_time < GET_CONTENT_RATE:
        print(f"Sleeping for {GET_CONTENT_RATE - now_time + get_content_time}s")
        time.sleep(GET_CONTENT_RATE - now_time + get_content_time)
    content_reponse = requests.get(url)
    get_content_time = time.time()
    content_reponse.raise_for_status()
    return content_reponse.json()


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


def get_content_page(content_name: str) -> Generator[List[Dict], None, None]:
    first_page = get_content(content_name)
    yield first_page["Results"]


if __name__ == "__main__":
    pass
