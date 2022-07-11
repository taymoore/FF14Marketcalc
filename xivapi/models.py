from typing import Any, Dict, Generator, List, Optional, Tuple, Type, Union
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

    # class Config:
    #     frozen = True


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
    Name: Optional[str]
    Url: str
    UrlType: Optional[str]


class Page(BaseModel):
    Pagination: Pagination
    Results: List[PageResult]


class Item(BaseModel):
    LevelItem: Optional[int]
    ID: int
    Name: str
    AetherialReduce: int

    class Config:
        frozen = True


# class ItemCollection(BaseCollectionModel[Item]):
#     class Config:
#         validate_assignment_strict = False


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


# Gathering Stuff

class GatheringPointBaseLink(BaseModel):
    Item0: Optional[List[int]]
    Item1: Optional[List[int]]
    Item2: Optional[List[int]]
    Item3: Optional[List[int]]
    Item4: Optional[List[int]]
    Item5: Optional[List[int]]
    Item6: Optional[List[int]]
    Item7: Optional[List[int]]

    def yield_gathering_point_base_id(self) -> Generator[int, None, None]:
        for index in range(8):
            item_list = getattr(self, f"Item{index}")
            if item_list is not None:
                for item_id in item_list:
                    yield item_id


class GatheringPointLink(BaseModel):
    GatheringPointBase: List[
        int
    ]  # links to gathering points (not gathering point base)


class GatheringItemPointLink(BaseModel):
    GatheringPoint: List[str]


class GameContentLinks(BaseModel):
    # FishParameter: Optional[GatheringItemLevelTable]
    # GatheringItem: Optional[GatheringItemLevelTable]
    GatheringPointBase: Optional[GatheringPointBaseLink]
    GatheringPoint: Optional[GatheringPointLink]
    GatheringItemPoint: Optional[GatheringItemPointLink]


class GatheringItemLevelConvertTable(BaseModel):
    GatheringItemLevel: int


class GatheringItem(BaseModel):
    GameContentLinks: Optional[GameContentLinks]
    GatheringItemLevel: Optional[GatheringItemLevelConvertTable]
    ID: int
    Item: Optional[Item]
    ItemTargetID: int


class GatheringPointBase(BaseModel):
    GameContentLinks: GameContentLinks
    GatheringLevel: int
    GatheringTypeTargetID: int
    ID: int
    Item0: Optional[GatheringItem]
    Item1: Optional[GatheringItem]
    Item2: Optional[GatheringItem]
    Item3: Optional[GatheringItem]
    Item4: Optional[GatheringItem]
    Item5: Optional[GatheringItem]
    Item6: Optional[GatheringItem]
    Item7: Optional[GatheringItem]

    def yield_gathering_items(self) -> Generator[GatheringItem, None, None]:
        for index in range(8):
            item = getattr(self, f"Item{index}")
            if item is not None:
                yield item


class ExportedGatheringPoint(BaseModel):
    GatheringTypeTargetID: int
    ID: int
    Patch: Optional[int]
    Radius: int
    Url: str
    X: float
    Y: float


class Map(BaseModel):
    ID: int
    MapFilename: str


class PlaceName(BaseModel):
    ID: int
    Name: str


class TerritoryType(BaseModel):
    ID: int
    Map: Map
    PlaceName: PlaceName


class GatheringPoint(BaseModel):
    ExportedGatheringPoint: Union[ExportedGatheringPoint, bool]
    GameContentLinks: GameContentLinks
    ID: int
    PlaceNameTargetID: int
    TerritoryTypeTargetID: int
