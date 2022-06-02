from typing import Any, Dict, List, Optional, Tuple, Type, Union
from pydantic import BaseModel
from pydantic_collections import BaseCollectionModel


class ClassJob(BaseModel):
    ID: int
    Icon: str
    Name: str
    Url: str
    Abbreviation: str


class Pagination(BaseModel):
    Page: int
    PageNext: Any
    PagePrev: Any
    PageTotal: int
    Results: int
    ResultsPerPage: int
    ResultsTotal: int


class PageResult(BaseModel):
    ID: int
    Name: str
    Url: str
    UrlType: Optional[str]


class Page(BaseModel):
    Pagination: Pagination
    Results: List[PageResult]


class ClassJobCategory(BaseModel):
    Name: str


class ClassJobInfo(BaseModel):
    Abbreviation: str
    ClassJobCategory: ClassJobCategory


class Item(BaseModel):
    LevelItem: int
    ID: int


class RecipeLevelTable(BaseModel):
    ClassJobLevel: int


class Recipe(BaseModel):
    ID: int
    ClassJob: ClassJob
    RecipeLevelTable: RecipeLevelTable
    AmountIngredient0: int
    AmountIngredient1: int
    AmountIngredient2: int
    AmountIngredient3: int
    AmountIngredient4: int
    AmountIngredient5: int
    AmountIngredient6: int
    AmountIngredient7: int
    AmountIngredient8: int
    AmountIngredient9: int
    AmountResult: int
    ItemResult: Item


# class RecipeCollection(BaseModel):
#     __root__: List[Recipe] = []


class RecipeCollection(BaseCollectionModel[Recipe]):
    class Config:
        validate_assignment_strict = False
