from typing import Any, Dict, List, Optional, Tuple, Type, Union
from pydantic import BaseModel
from pydantic_collections import BaseCollectionModel


class ClassJobCategory(BaseModel):
    Name: str


class ClassJob(BaseModel):
    ID: int
    Icon: str
    Name: str
    Url: str
    Abbreviation: str
    ClassJobCategory: Union[int, ClassJobCategory]

    class Config:
        frozen = True


class ClassJobCollection(BaseCollectionModel[ClassJob]):
    class Config:
        validate_assignment_strict = False


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


class Item(BaseModel):
    LevelItem: int
    ID: int
    Name: str

    class Config:
        frozen = True


class RecipeLevelTable(BaseModel):
    ClassJobLevel: int

    class Config:
        frozen = True


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
    ItemIngredientRecipe0: Optional[Tuple["Recipe", ...]]
    ItemIngredientRecipe1: Optional[Tuple["Recipe", ...]]
    ItemIngredientRecipe2: Optional[Tuple["Recipe", ...]]
    ItemIngredientRecipe3: Optional[Tuple["Recipe", ...]]
    ItemIngredientRecipe4: Optional[Tuple["Recipe", ...]]
    ItemIngredientRecipe5: Optional[Tuple["Recipe", ...]]
    ItemIngredientRecipe6: Optional[Tuple["Recipe", ...]]
    ItemIngredientRecipe7: Optional[Tuple["Recipe", ...]]
    ItemIngredientRecipe8: Optional[Tuple["Recipe", ...]]
    ItemIngredientRecipe9: Optional[Tuple["Recipe", ...]]
    AmountResult: int
    ItemResult: Item

    class Config:
        frozen = True


class RecipeCollection(BaseCollectionModel[Recipe]):
    class Config:
        validate_assignment_strict = False
