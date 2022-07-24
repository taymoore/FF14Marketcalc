from datetime import timedelta
import enum
import logging
import time
from typing import Callable, Any, Dict, Iterable, Mapping, Optional, Tuple, List, Union

from pydantic import BaseModel
from universalis.models import Listings
from xivapi.models import Item, Recipe
from xivapi.xivapi import (
    get_classjob_doh_list,
    get_recipes,
    get_recipes_up_to_level,
    search_recipes,
)
from universalis.universalis import get_listings
from universalis.universalis import save_to_disk as universalis_save_to_disk

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


def get_actions(
    recipe: Recipe, world: Union[str, int], refresh_cache: bool = False
) -> List[Action]:
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
                            action.cost * action.quantity
                            for action in get_actions(
                                ingredient_recipe, world, refresh_cache
                            )
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
            cost_to_buy = get_listings(
                item.ID, world, cache_timeout_s=60 if refresh_cache else None
            ).minPrice
            _logger.log(
                logging.DEBUG,
                f"Ingredient for {recipe.ItemResult.Name}, {item.Name} to buy costs {quantity} x {cost_to_buy}: {quantity * cost_to_buy}",
            )
            action_list.append(
                determine_action(
                    quantity, item, cost_to_make, craft_recipe, cost_to_buy
                )
            )

    _logger.log(
        logging.DEBUG,
        f"Actions for {recipe.ItemResult.Name} are: {[(action.item.Name, action.aquire_action.name, action.quantity, action.cost) for action in action_list]}",
    )
    return action_list


def determine_action(
    quantity: int,
    item: Item,
    cost_to_make: Optional[float],
    cost_to_buy: Optional[float],
    craft_recipe: Recipe,
):
    if cost_to_buy is None:
        if cost_to_make is None:
            return Action(
                item=item,
                aquire_action=AquireAction.GATHER,
                cost=DEFAULT_COST,
                quantity=quantity,
            )
        elif cost_to_make < GATHER_COST:
            return Action(
                item=item,
                recipe=craft_recipe,
                aquire_action=AquireAction.CRAFT,
                cost=cost_to_make,
                quantity=quantity,
            )
        else:
            return Action(
                item=item,
                aquire_action=AquireAction.GATHER,
                cost=GATHER_COST,
                quantity=quantity,
            )
    elif cost_to_make is None:
        if cost_to_buy < GATHER_COST:
            return Action(
                item=item,
                aquire_action=AquireAction.BUY,
                cost=cost_to_buy,
                quantity=quantity,
            )
        else:
            return Action(
                item=item,
                aquire_action=AquireAction.GATHER,
                cost=GATHER_COST,
                quantity=quantity,
            )
    elif cost_to_buy < GATHER_COST or cost_to_make < GATHER_COST:
        if cost_to_buy < cost_to_make:
            return Action(
                item=item,
                aquire_action=AquireAction.BUY,
                cost=cost_to_buy,
                quantity=quantity,
            )
        else:
            return Action(
                item=item,
                recipe=craft_recipe,
                aquire_action=AquireAction.CRAFT,
                cost=cost_to_make,
                quantity=quantity,
            )
    else:
        return Action(
            item=item,
            aquire_action=AquireAction.GATHER,
            cost=GATHER_COST,
            quantity=quantity,
        )


def get_profit(
    recipe: Recipe, world: Union[str, int], refresh_cache: bool = False
) -> float:
    revenue = get_revenue_(recipe.ItemResult.ID, world, refresh_cache)
    _logger.log(logging.DEBUG, f"Revenue for {recipe.ItemResult.Name} is {revenue}")
    if revenue == 0:
        return 0
    return revenue - sum(
        [
            action.cost * action.quantity
            for action in get_actions(recipe, world, refresh_cache=refresh_cache)
        ]
    )


def get_actions_dict(recipe, world, refresh_cache: bool = False):
    def aquire_actions(
        recipe: Recipe,
        quantity: int,
        actions_dict: Dict[int, List[List[Action]]],
        actions_level: int,
    ) -> Dict[int, List[List[Action]]]:
        actions = get_actions(recipe, world, refresh_cache)
        for action in actions:
            action.quantity *= quantity
        actions_dict.setdefault(actions_level, []).append(actions)
        actions_level += 1
        for action in actions:
            if action.aquire_action == AquireAction.CRAFT:
                actions_dict = aquire_actions(
                    action.recipe, action.quantity, actions_dict, actions_level
                )
        return actions_dict

    actions_dict = aquire_actions(recipe, 1, {}, 0)
    return actions_dict


def get_revenue_(id: int, world, refresh_cache: bool = False) -> float:
    _logger.warning("get_revenue_ is deprecated. Use get_revenue instead.")
    listings = get_listings(id, world, cache_timeout_s=60 if refresh_cache else None)
    return get_revenue(listings)


def get_revenue(listings: Listings) -> float:
    history_price = [listing.pricePerUnit for listing in listings.recentHistory]
    # history_price_avg = sum(history_price) / len(history_price)
    return (
        min(min(history_price), listings.minPrice)
        if len(history_price) > 0
        else listings.minPrice
    ) * 0.95


def print_recipe(recipe: Recipe, world: Union[str, int]) -> str:
    string = ""
    string += f"{recipe.ItemResult.Name} sells for: {get_revenue_(recipe.ItemResult.ID, world, True):,.0f} (inc. gst)\n"
    string += f"Expected profit: {get_profit(recipe, world, True):,.0f}\n"

    listings = get_listings(id=recipe.ItemResult.ID, world=world, cache_timeout_s=60)
    string += f"Quantity for sale: {len(listings.listings)}\n"

    history_price = [listing.pricePerUnit for listing in listings.recentHistory]
    if len(history_price) > 0:
        string += f"Average history: {sum(history_price)/len(history_price):,.0f}\n"
        string += f"Min history: {min(history_price):,.0f}\n"
    else:
        string += "No price history\n"

    actions_level = 0

    actions_dict = get_actions_dict(recipe, world, refresh_cache=True)
    for actions_level, action_list in actions_dict.items():
        string += f"Level {actions_level}:\n"
        for actions in action_list:
            for action in actions:
                string += f"  {action.aquire_action.name} {action.item.Name} {action.quantity} x {action.cost}\n"
    return string


def log_time(
    msg: str,
    old_time: Optional[float],
    logger: logging.Logger = None,
    level: int = logging.INFO,
) -> float:
    new_time = time.time()
    if old_time is not None:
        if logger:
            logger.log(level, f"{msg} took {timedelta(seconds=new_time - old_time)}")
        else:
            print(f"{msg} took {timedelta(seconds=new_time - old_time)}")
    return new_time


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # _logger.setLevel(logging.INFO)
    world = 55

    print("getting recipe")
    get_listings(1294, 55)
    print("2")
    get_listings(1294, 55)
    print("3")
    get_listings(1294, 55)
    universalis_save_to_disk()

    # # recipe_collection = search_recipies("Polished Slate Grinding Wheel")
    # # recipe: Recipe
    # # for recipe in recipe_collection:
    # #     print_recipe(recipe, 55)

    # # print(get_classjob_doh_list())
    # player_class_list: List[Tuple[int, int]] = [
    #     (8, 67),  # CRP
    #     (9, 67),  # BSM
    #     (10, 70),  # ARM
    #     (11, 70),  # GSM
    #     (12, 20),  # LTW
    #     # (13, 70),  # WVR
    #     # (14, 70),  # ALC
    #     # (15, 70),  # CUL
    # ]

    # recipes: List[Recipe] = []
    # for classjob_id, classjob_level in player_class_list:
    #     recipes.extend(
    #         get_recipes_up_to_level(
    #             classjob_id=classjob_id, classjob_level_max=classjob_level
    #         )
    #     )
    # recipe_profit_list: List[
    #     Tuple[float, Listings, Recipe]
    # ] = []  # profit, velocity, recipe
    # recipe: Recipe
    # for recipe in recipes:
    #     profit = get_profit(recipe, world)
    #     if profit != 0:
    #         recipe_profit_list.append(
    #             (
    #                 profit,
    #                 get_listings(recipe.ItemResult.ID, world).regularSaleVelocity,
    #                 recipe,
    #             )
    #         )
    # recipe_profit_list.sort(key=lambda recipe_tuple: recipe_tuple[0] * recipe_tuple[1])
    # for recipe_tuple in recipe_profit_list:
    #     print(
    #         f"{recipe_tuple[2].ClassJob.Abbreviation}: {recipe_tuple[2].ItemResult.Name}: {recipe_tuple[0]:,.0f} at velocity {recipe_tuple[1]:.2f}. Score {recipe_tuple[0] * recipe_tuple[1]:,.0f}"
    #     )
    # print()
    # print(print_recipe(recipe_profit_list[-1][2], world))

    # # recipes = get_recipes_up_to_level(classjob_id=8, classjob_level_max=3)
    # # recipe_profit_list: List[Tuple[int, Recipe]] = []
    # # recipe: Recipe
    # # for recipe in recipes:
    # #     profit = get_profit(recipe, world)
    # #     if profit != 0:
    # #         recipe_profit_list.append((profit, recipe))
    # # recipe_profit_list.sort(key=lambda recipe_tuple: recipe_tuple[0])
    # # for recipe_tuple in recipe_profit_list:
    # #     print(f"{recipe_tuple[1].ItemResult.Name}: {recipe_tuple[0]}")
    # # print()
    # # print_recipe(recipe_profit_list[-1][1], world)
    # # # # print(get_listings(recipes[0].ItemResult.ID, 55))
    # # # # print(recipes)
