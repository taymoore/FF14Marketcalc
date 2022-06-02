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
    Name: str


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
    ItemIngredient0: Item
    ItemIngredient1: Optional[Item]
    ItemIngredient2: Optional[Item]
    ItemIngredient3: Optional[Item]
    ItemIngredient4: Optional[Item]
    ItemIngredient5: Optional[Item]
    ItemIngredient6: Optional[Item]
    ItemIngredient7: Optional[Item]
    ItemIngredient8: Optional[Item]
    ItemIngredient9: Optional[Item]
    ItemIngredientRecipe0: Optional[List["Recipe"]]
    ItemIngredientRecipe1: Optional[List["Recipe"]]
    ItemIngredientRecipe2: Optional[List["Recipe"]]
    ItemIngredientRecipe3: Optional[List["Recipe"]]
    ItemIngredientRecipe4: Optional[List["Recipe"]]
    ItemIngredientRecipe5: Optional[List["Recipe"]]
    ItemIngredientRecipe6: Optional[List["Recipe"]]
    ItemIngredientRecipe7: Optional[List["Recipe"]]
    ItemIngredientRecipe8: Optional[List["Recipe"]]
    ItemIngredientRecipe9: Optional[List["Recipe"]]
    AmountResult: int
    ItemResult: Item


# class RecipeCollection(BaseModel):
#     __root__: List[Recipe] = []


class RecipeCollection(BaseCollectionModel[Recipe]):
    class Config:
        validate_assignment_strict = False
