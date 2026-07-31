from __future__ import annotations

from typing import Literal


InventoryPolicy = Literal[
    "ignore",
    "staple",
    "tracked",
]


FOOD_NAME_ALIASES = {
    "开水": "水",
    "热水": "水",
    "温水": "水",
    "凉水": "水",
    "冷水": "水",
    "清水": "水",
    "冰水": "水",
    "食盐": "盐",
    "白砂糖": "白糖",
    "植物油": "食用油",
    "色拉油": "食用油",
}


IGNORED_FOODS = {
    "水",
    "冰块",
}


STAPLE_FOODS = {
    "食用油",
    "花生油",
    "菜籽油",
    "玉米油",
    "葵花籽油",
    "橄榄油",
    "芝麻油",
    "香油",
    "盐",
    "白糖",
    "生抽",
    "老抽",
    "酱油",
    "料酒",
    "醋",
    "淀粉",
    "生粉",
    "黑胡椒",
    "白胡椒",
}


def canonical_food_name(
    value: str,
) -> str:
    name = value.strip()

    return FOOD_NAME_ALIASES.get(
        name,
        name,
    )


def inventory_policy_for_food(
    value: str,
) -> InventoryPolicy:
    name = canonical_food_name(value)

    if name in IGNORED_FOODS:
        return "ignore"

    if name in STAPLE_FOODS:
        return "staple"

    return "tracked"
