from typing import Any, Dict, Generator, List, Optional, Tuple, Type, Union
from pydantic import BaseModel

class ItemData(BaseModel):
    name: str
    id: int
    ilvl: int
    tradeable: int
    rarity: int
    unlistable: Optional[int]
    reducible: int
    collectable: int
    icon: int
    nodes: List[int]
    reducesTo: List[int]

class PartialObject(BaseModel):
    i: int  # id
    n: str  # name
    l: int  # level
    c: Optional[int]
    t: int
    z: Optional[int]
    s: Optional[int]
    lt: Optional[str]
    ti: Optional[List[int]]

class Partial(BaseModel):
    type: str
    id: str
    obj: PartialObject

class Item(BaseModel):
    item: ItemData
    partials: List[Partial]