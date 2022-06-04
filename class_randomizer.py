from typing import Dict, List, Optional, Tuple, Union
import requests
import random
from pydantic import BaseModel

# Assumes each player has at least one choice
def class_randomizer(
    players_dict: Dict[str, List[Tuple[str, str]]] = {
        "Dan": [("Whm", "healer"), ("Blm", "dps"), ("Drk", "tank"), ("Rpr", "dps")],
        "Kattie": [("Nnj", "dps")],  # ("War", "tank"),
        # "Helen": [("Brd", "dps"), ("Whm", "healer")],
        "Kai": [("Ast", "healer"), ("Gnb", "Tank"), ("Dnc", "dps"), ("Blm", "dps")],
        "Taylor": [
            ("Sge", "healer"),
            ("Pld", "tank"),
            ("Sch", "healer"),
            ("Sam", "dps"),
            ("Sum", "dps"),
            ("Pug", "dps"),
            ("War", "tank"),
        ],
    }
):
    # Restructure based on role
    classes_dict: Dict[str, List[Tuple[str, str]]] = {}  # {role, [(player_name, job)]}
    for player_name, choices_list in players_dict.items():
        for choice_tuple in choices_list:
            job, role = choice_tuple
            role_list = classes_dict.setdefault(role, [])
            role_list.append((player_name, job))

    assert len(classes_dict["tank"]) >= 1
    assert len(classes_dict["healer"]) >= 1
    assert len(classes_dict["dps"]) >= 2

    class Option(BaseModel):
        player_name: str
        job: str
        role: str

    valid_options: List[List[Option]] = []
    option_indexer = {"tank": 0, "healer": 0, "dps1": 0, "dps2": 0}
    # Returns Tuple[True if end of branch / overflow, True if this option is invalid]
    def fill_option(
        option_list: List[Option],
        classes_dict: Dict[str, List[Tuple[str, str]]],
        option_indexer: Dict[str, int],
        option_index: int,
    ) -> Tuple[Optional[bool], bool]:
        option_role = list(option_indexer.keys())[option_index]
        class_role = "dps" if "dps" in option_role else option_role
        choice_tuple = classes_dict[class_role][option_indexer[option_role]]
        player_name, job = choice_tuple

        invalid_option = False
        if option_indexer.get("dps1") == option_indexer.get("dps2"):
            invalid_option = True

        for option in option_list:
            if option.player_name == player_name:
                invalid_option = True
                break

        if not invalid_option:
            option_list.append(
                Option(player_name=player_name, job=job, role=class_role)
            )

        if option_index < len(option_indexer) - 1:
            overflow_bool, invalid_option_nested = fill_option(
                option_list, classes_dict, option_indexer, option_index + 1
            )
            invalid_option = invalid_option or invalid_option_nested
            if overflow_bool:
                option_indexer[option_role] += 1
        else:
            option_indexer[option_role] += 1
        if option_indexer[option_role] >= len(classes_dict[class_role]):
            option_indexer[option_role] = 0
            return (True, invalid_option)
        else:
            return (False, invalid_option)

    fill_options_semaphore = True
    while fill_options_semaphore:
        option_list: List[Option] = []
        overflow_bool, invalid_option = fill_option(
            option_list, classes_dict, option_indexer, 0
        )
        if overflow_bool:
            fill_options_semaphore = False
        if not invalid_option:
            # Remove identical configuration with alternate arrangements
            for configuration in valid_options:
                invalid_option = True
                for option in option_list:
                    if option not in configuration:
                        invalid_option = False
                        break
                if invalid_option:
                    break
            if not invalid_option:
                valid_options.append(option_list)

    return random.choice(valid_options)


if __name__ == "__main__":
    options = class_randomizer()
    for option in options:
        print(f"{option.player_name}: {option.job} ({option.role})")
