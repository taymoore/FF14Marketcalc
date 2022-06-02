from xivapi.xivapi import get_recipes
from universalis.universalis import get_listings

if __name__ == "__main__":
    recipes = get_recipes(classjob_id=8, classjob_level=67)
    print(get_listings(recipes[0].ItemResult.ID, 55))
    # print(recipes)
