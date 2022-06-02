from typing import TypeVar, Union
from pydantic import BaseModel
import requests

from universalis.models import Listings


def get_listings(id: int, world: Union[int, str]) -> Listings:
    url = f"https://universalis.app/api/{world}/{id}"
    content_response = requests.get(url)
    content_response.raise_for_status()
    return Listings.parse_obj(content_response.json())
