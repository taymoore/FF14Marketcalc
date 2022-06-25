# from typing import Dict, Generator, List, Tuple
# from pydantic import BaseModel
# from xivapi.models import Page, Recipe
# from xivapi.xivapi import get_content, get_content_pages


# class RecipeClassJobLevelIndex(BaseModel):
#     results_total: int
#     recipes: List[Recipe]


# class RecipeManager:
#     def __init__(self) -> None:
#         self.recipe_classjob_level_index_dict: Dict[
#             Tuple[int, int], RecipeClassJobLevelIndex
#         ] = {}

#     def yeild_recipe(
#         self, classjob_id: int, classjob_level: int
#     ) -> Generator[Recipe, None, None]:
#         first_page: Page = get_content(
#             f"search?filters=RecipeLevelTable.ClassJobLevel={classjob_level},ClassJob.ID={classjob_id}",
#             Page,
#         )
