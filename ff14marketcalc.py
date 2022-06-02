import enum
import logging
from typing import Tuple, List, Union
from xivapi.models import Item, Recipe
from xivapi.xivapi import get_recipes
from universalis.universalis import get_listings

_logger = logging.getLogger(__name__)

DEFAULT_COST = 50000


class AquireAction(enum.Enum):
    BUY = enum.auto()
    MAKE = enum.auto()
    FARM = enum.auto()


def get_best_cost(
    recipe: Recipe, world: Union[str, int]
) -> List[Tuple[Item, AquireAction, int]]:
    action_list: List[Tuple[Item, AquireAction, int]] = []
    for ingredient_index in range(9):
        quantity: int = getattr(recipe, f"AmountIngredient{ingredient_index}")
        item: Item = getattr(recipe, f"ItemIngredient{ingredient_index}")
        if item:
            cost_to_buy = get_listings(item.ID, world).minPrice
            _logger.log(
                logging.INFO,
                f"Ingredient for {recipe.ItemResult.Name}, {item.Name} to buy costs {quantity} x {cost_to_buy}: {quantity * cost_to_buy}",
            )
            ingredient_recipes = getattr(
                recipe, f"ItemIngredientRecipe{ingredient_index}"
            )
            cost_to_make = 0
            if ingredient_recipes:
                for ingredient_recipe in ingredient_recipes:
                    cost_to_make_ingredient = sum(
                        [
                            action[2]
                            for action in get_best_cost(ingredient_recipe, world)
                        ]
                    )
                    cost_to_make = (
                        min(cost_to_make, cost_to_make_ingredient)
                        if cost_to_make > 0
                        else cost_to_make_ingredient
                    )
                _logger.log(
                    logging.INFO,
                    f"Ingredient for {recipe.ItemResult.Name}, {item.Name} to make costs {quantity} x {cost_to_make}: {quantity * cost_to_make}",
                )
            if cost_to_make == 0 or cost_to_buy < cost_to_make:
                action_list.append((item, AquireAction.BUY, cost_to_buy * quantity))
            elif cost_to_buy > 0:
                action_list.append((item, AquireAction.MAKE, cost_to_make * quantity))
            else:
                _logger.log(
                    logging.WARN,
                    f"Item {recipe.ItemResult} has no cost! Using {DEFAULT_COST}",
                )
                action_list.append((item, AquireAction.FARM, DEFAULT_COST * quantity))
    _logger.log(
        logging.INFO,
        f"Actions for {recipe.ItemResult.Name} are: {[(action[0].Name, action[1].name, action[2]) for action in action_list]}",
    )
    return action_list


def get_profit(recipe: Recipe, world: Union[str, int]) -> int:
    revenue = get_listings(recipe.ItemResult.ID, world).minPrice
    _logger.log(logging.INFO, f"Revenue for {recipe.ItemResult.Name} is {revenue}")
    if revenue == 0:
        return 0
    return revenue - sum([action[2] for action in get_best_cost(recipe, world)])


if __name__ == "__main__":
    # logging.basicConfig(level=logging.INFO)
    logging.basicConfig()
    _logger.setLevel(logging.INFO)
    recipes = get_recipes(classjob_id=8, classjob_level=67)
    recipe: Recipe
    for recipe in recipes:
        print(f"{recipe.ItemResult.Name}: {get_profit(recipe, 55):}")
    # print(get_listings(recipes[0].ItemResult.ID, 55))
    # print(recipes)
