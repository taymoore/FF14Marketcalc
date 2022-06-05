import enum
from functools import cache
import logging
from typing import Callable, Any, Dict, Iterable, Mapping, Optional, Tuple, List, Union

from pydantic import BaseModel
from xivapi.models import Item, Recipe
from xivapi.xivapi import (
    get_classjob_doh_list,
    get_recipes,
    get_recipes_up_to_level,
    search_recipes,
)
from universalis.universalis import get_listings

_logger = logging.getLogger(__name__)

DEFAULT_COST = 100000
GATHER_COST = 1000000


class AquireAction(enum.Enum):
    BUY = enum.auto()
    CRAFT = enum.auto()
    GATHER = enum.auto()


class Action(BaseModel):
    item: Item
    recipe: Optional[Recipe] = None
    aquire_action: AquireAction
    cost: int
    quantity: int


@cache
def get_actions(recipe: Recipe, world: Union[str, int]) -> List[Action]:
    action_list: List[Action] = []
    for ingredient_index in range(9):
        quantity: int = getattr(recipe, f"AmountIngredient{ingredient_index}")
        item: Item = getattr(recipe, f"ItemIngredient{ingredient_index}")
        if item:
            ingredient_recipes = getattr(
                recipe, f"ItemIngredientRecipe{ingredient_index}"
            )
            cost_to_make = 0
            craft_recipe = None
            if ingredient_recipes:
                for ingredient_recipe in ingredient_recipes:
                    cost_to_make_ingredient = sum(
                        [
                            action.cost
                            for action in get_actions(ingredient_recipe, world)
                        ]
                    )
                    if cost_to_make == 0 or cost_to_make_ingredient < cost_to_make:
                        cost_to_make = cost_to_make_ingredient
                        craft_recipe = ingredient_recipe
                _logger.log(
                    logging.DEBUG,
                    f"Ingredient for {recipe.ItemResult.Name}, {item.Name} to make costs {quantity} x {cost_to_make}: {quantity * cost_to_make}",
                )
            # Assumes infinite availablity of this item at minPrice
            cost_to_buy = get_listings(item.ID, world).minPrice
            # cost_to_buy = get_listings(item.ID, world).minPrice
            _logger.log(
                logging.DEBUG,
                f"Ingredient for {recipe.ItemResult.Name}, {item.Name} to buy costs {quantity} x {cost_to_buy}: {quantity * cost_to_buy}",
            )
            if cost_to_buy == 0:
                if cost_to_make == 0:
                    _logger.log(
                        logging.WARN,
                        f"Item {recipe.ItemResult} has no cost! Using {DEFAULT_COST}",
                    )
                    action_list.append(
                        Action(
                            item=item,
                            aquire_action=AquireAction.GATHER,
                            cost=DEFAULT_COST,
                            quantity=quantity,
                        )
                    )
                elif cost_to_make < GATHER_COST:
                    action_list.append(
                        Action(
                            item=item,
                            recipe=craft_recipe,
                            aquire_action=AquireAction.CRAFT,
                            cost=cost_to_make,
                            quantity=quantity,
                        )
                    )
                else:
                    action_list.append(
                        Action(
                            item=item,
                            aquire_action=AquireAction.GATHER,
                            cost=GATHER_COST,
                            quantity=quantity,
                        )
                    )
            elif cost_to_make == 0:
                if cost_to_buy < GATHER_COST:
                    action_list.append(
                        Action(
                            item=item,
                            aquire_action=AquireAction.BUY,
                            cost=cost_to_buy,
                            quantity=quantity,
                        )
                    )
                else:
                    action_list.append(
                        Action(
                            item=item,
                            aquire_action=AquireAction.GATHER,
                            cost=GATHER_COST,
                            quantity=quantity,
                        )
                    )
            elif cost_to_buy < GATHER_COST or cost_to_make < GATHER_COST:
                if cost_to_buy < cost_to_make:
                    action_list.append(
                        Action(
                            item=item,
                            aquire_action=AquireAction.BUY,
                            cost=cost_to_buy,
                            quantity=quantity,
                        )
                    )
                else:
                    action_list.append(
                        Action(
                            item=item,
                            recipe=craft_recipe,
                            aquire_action=AquireAction.CRAFT,
                            cost=cost_to_make,
                            quantity=quantity,
                        )
                    )
            else:
                action_list.append(
                    Action(
                        item=item,
                        aquire_action=AquireAction.GATHER,
                        cost=GATHER_COST,
                        quantity=quantity,
                    )
                )

    _logger.log(
        logging.DEBUG,
        f"Actions for {recipe.ItemResult.Name} are: {[(action.item.Name, action.aquire_action.name, action.quantity, action.cost) for action in action_list]}",
    )
    return action_list


def get_profit(recipe: Recipe, world: Union[str, int]) -> int:
    revenue = get_listings(recipe.ItemResult.ID, world).averagePrice
    _logger.log(logging.DEBUG, f"Revenue for {recipe.ItemResult.Name} is {revenue}")
    if revenue == 0:
        return 0
    return revenue - sum([action.cost for action in get_actions(recipe, world)])


def get_actions_dict(recipe, world):
    def aquire_actions(
        recipe: Recipe, actions_dict: Dict[int, List[List[Action]]], actions_level: int
    ) -> Dict[int, List[List[Action]]]:
        actions_dict.setdefault(actions_level, []).append(
            actions := get_actions(recipe, world)
        )
        actions_level += 1
        for action in actions:
            if action.aquire_action == AquireAction.CRAFT:
                actions_dict = aquire_actions(
                    action.recipe, actions_dict, actions_level
                )
        return actions_dict

    actions_dict = aquire_actions(recipe, {}, 0)
    return actions_dict


def print_recipe(recipe: Recipe, world: Union[str, int]) -> str:
    # logger = logging.getLogger("recipe_output")
    # logger.setLevel(logging.INFO)
    # logger.info(
    #     f"{recipe.ItemResult.Name} expected profit: {get_profit(recipe, world)}"
    # )
    string = ""
    string += (
        f"{recipe.ItemResult.Name} expected profit: {get_profit(recipe, world):,.0f}\n"
    )
    actions_level = 0

    actions_dict = get_actions_dict(recipe, world)
    for actions_level, action_list in actions_dict.items():
        # logger.info(f"Level {actions_level}:")
        string += f"Level {actions_level}:\n"
        for actions in action_list:
            for action in actions:
                # logger.info(
                #     f"  {action.aquire_action.name} {action.item.Name} {action.quantity} x {action.cost}"
                # )
                string += f"  {action.aquire_action.name} {action.item.Name} {action.quantity} x {action.cost}\n"
    return string


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # _logger.setLevel(logging.INFO)
    world = 55

    # recipe_collection = search_recipies("Polished Slate Grinding Wheel")
    # recipe: Recipe
    # for recipe in recipe_collection:
    #     print_recipe(recipe, 55)

    # print(get_classjob_doh_list())
    player_class_list: List[Tuple[int, int]] = [
        (8, 67),  # CRP
        (9, 67),  # BSM
        (10, 70),  # ARM
        (11, 70),  # GSM
        (12, 20),  # LTW
        # (13, 70),  # WVR
        # (14, 70),  # ALC
        # (15, 70),  # CUL
    ]

    recipes: List[Recipe] = []
    for classjob_id, classjob_level in player_class_list:
        recipes.extend(
            get_recipes_up_to_level(
                classjob_id=classjob_id, classjob_level_max=classjob_level
            )
        )
    recipe_profit_list: List[Tuple[int, float, Recipe]] = []  # profit, velocity, recipe
    recipe: Recipe
    for recipe in recipes:
        profit = get_profit(recipe, world)
        if profit != 0:
            recipe_profit_list.append(
                (
                    profit,
                    get_listings(recipe.ItemResult.ID, world).regularSaleVelocity,
                    recipe,
                )
            )
    recipe_profit_list.sort(key=lambda recipe_tuple: recipe_tuple[0] * recipe_tuple[1])
    for recipe_tuple in recipe_profit_list:
        print(
            f"{recipe_tuple[2].ClassJob.Abbreviation}: {recipe_tuple[2].ItemResult.Name}: {recipe_tuple[0]:,.0f} at velocity {recipe_tuple[1]:.2f}. Score {recipe_tuple[0] * recipe_tuple[1]:,.0f}"
        )
    print()
    print(print_recipe(recipe_profit_list[-1][2], world))

    # recipes = get_recipes_up_to_level(classjob_id=8, classjob_level_max=3)
    # recipe_profit_list: List[Tuple[int, Recipe]] = []
    # recipe: Recipe
    # for recipe in recipes:
    #     profit = get_profit(recipe, world)
    #     if profit != 0:
    #         recipe_profit_list.append((profit, recipe))
    # recipe_profit_list.sort(key=lambda recipe_tuple: recipe_tuple[0])
    # for recipe_tuple in recipe_profit_list:
    #     print(f"{recipe_tuple[1].ItemResult.Name}: {recipe_tuple[0]}")
    # print()
    # print_recipe(recipe_profit_list[-1][1], world)
    # # # print(get_listings(recipes[0].ItemResult.ID, 55))
    # # # print(recipes)
