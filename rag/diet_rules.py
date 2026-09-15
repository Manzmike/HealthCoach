#!/usr/bin/env python3
"""Diet presets + exclusion toggles that gate which foods are selectable.

Two-layer model, matching how people actually think about their diet:
  1. Pick ONE preset (or "whole_food" for no preset restrictions at all).
  2. Stack any number of exclusion toggles on top (e.g. keto + no_dairy).

Every food in the catalog gets exactly one FOOD_CATEGORY. A preset EXCLUDES a set of
categories; a toggle excludes a set of specific food ids or a category. A food is selectable
only if it survives both the preset's exclusions and every active toggle's exclusions.

This is a real, inspectable rule engine — no ranking, no evidence, just "does this food fit
what you said you'd eat." Pair with candidate_manager.py for the evidence/grade side.
"""

from __future__ import annotations

from typing import Any

# ------------------------------------------------------------------ food -> category
# One category per food id in supplement_audit.WHOLE_FOOD_CATALOG (116 total).
FOOD_CATEGORY: dict[str, str] = {
    # herbs / spices / condiments
    "oregano": "herb_spice", "saffron_food": "herb_spice", "garlic_food": "herb_spice",
    "ginger_food": "herb_spice", "cinnamon_food": "herb_spice", "turmeric_food": "herb_spice",
    "parsley": "herb_spice", "cilantro": "herb_spice",
    # sweeteners
    "honey_treats": "sweetener", "dark_chocolate": "sweetener",
    # fruits
    "blueberries": "fruit", "tamarind": "fruit", "apples": "fruit", "bananas": "fruit",
    "strawberries": "fruit", "raspberries": "fruit", "blackberries": "fruit", "oranges": "fruit",
    "grapefruit": "fruit", "lemons": "fruit", "limes": "fruit", "kiwi": "fruit", "mango": "fruit",
    "pineapple": "fruit", "papaya": "fruit", "watermelon": "fruit", "grapes": "fruit",
    "cherries": "fruit", "peaches": "fruit", "pears": "fruit", "plums": "fruit",
    "pomegranate": "fruit", "dates": "fruit", "figs": "fruit",
    # leafy / cruciferous / non-starchy vegetables
    "spinach": "vegetable", "kale": "vegetable", "broccoli": "vegetable", "cauliflower": "vegetable",
    "brussels_sprouts": "vegetable", "cabbage": "vegetable", "tomatoes": "vegetable",
    "bell_peppers": "vegetable", "onions": "vegetable", "mushrooms": "vegetable",
    "cooked_mushrooms": "vegetable", "asparagus": "vegetable", "zucchini": "vegetable",
    "cucumber": "vegetable", "celery": "vegetable", "lettuce": "vegetable", "arugula": "vegetable",
    "watercress": "vegetable", "collard_greens": "vegetable", "swiss_chard": "vegetable",
    "eggplant": "vegetable", "radishes": "vegetable", "beets": "vegetable", "seaweed": "vegetable",
    # starchy vegetables
    "carrots": "starchy_veg", "sweet_potatoes": "starchy_veg", "potatoes": "starchy_veg",
    "butternut_squash": "starchy_veg", "pumpkin": "starchy_veg",
    # grains
    "oats": "grain", "quinoa": "grain", "brown_rice": "grain", "barley": "grain",
    "millet": "grain", "buckwheat": "grain", "farro": "grain", "popcorn": "grain",
    "wild_rice": "grain",
    # legumes
    "lentils": "legume", "chickpeas": "legume", "black_beans": "legume", "kidney_beans": "legume",
    "pinto_beans": "legume", "navy_beans": "legume", "edamame": "legume", "green_peas": "legume",
    # nuts / seeds
    "almonds": "nut_seed", "walnuts": "nut_seed", "pecans": "nut_seed", "pistachios": "nut_seed",
    "cashews": "nut_seed", "brazil_nuts": "nut_seed", "hazelnuts": "nut_seed", "peanuts": "nut_seed",
    "chia_seeds": "nut_seed", "flaxseeds": "nut_seed", "pumpkin_seeds": "nut_seed",
    "sunflower_seeds": "nut_seed", "hemp_seeds": "nut_seed", "sesame_seeds": "nut_seed",
    # eggs
    "eggs": "egg", "fish_eggs": "egg",
    # poultry
    "chicken": "poultry", "turkey": "poultry",
    # red meat
    "lean_beef": "red_meat", "lamb": "red_meat", "pork": "red_meat",
    # organ meat / collagen
    "beef_liver": "organ_meat", "beef_heart": "organ_meat", "gelatin_broth": "organ_meat",
    # fish / seafood
    "salmon": "fish_seafood", "sardines": "fish_seafood", "mackerel": "fish_seafood",
    "oysters": "fish_seafood",
    # dairy
    "plain_yogurt": "dairy", "kefir": "dairy", "pasteurized_dairy": "dairy",
    # fermented (non-dairy)
    "kimchi": "fermented", "sauerkraut": "fermented",
    # plant-derived fats — split out from "fruit"/generic "fat_oil" so keto/paleo (which don't
    # exclude this category) correctly keep avocado/olive oil available, while carnivore (which
    # does exclude it) correctly excludes them as plant foods, not lumped in with animal fats.
    "avocado": "plant_fat", "extra_virgin_olive_oil": "plant_fat", "coconut": "plant_fat",

    # ---- second expansion batch: user-supplied specific varieties/cuts ----
    "gala_apples": "fruit", "fuji_apples": "fruit", "honeycrisp_apples": "fruit", "granny_smith_apples": "fruit", "red_delicious_apples": "fruit", "golden_delicious_apples": "fruit", "pink_lady_apples": "fruit", "cosmic_crisp_apples": "fruit", "plantains": "fruit", "cranberries": "fruit", "mulberries": "fruit", "elderberries": "fruit", "goji_berries_unsweetened": "fruit", "golden_berries": "fruit", "amla_indian_gooseberry": "fruit", "navel_oranges": "fruit", "valencia_oranges": "fruit", "blood_oranges": "fruit", "mandarins": "fruit", "clementines": "fruit", "cantaloupe": "fruit", "honeydew_melon": "fruit", "nectarines": "fruit", "apricots": "fruit", "mangoes": "fruit", "guava": "fruit", "lychee": "fruit", "passion_fruit": "fruit", "dragon_fruit": "fruit", "star_fruit": "fruit", "jackfruit": "fruit", "soursop": "fruit", "persimmon": "fruit", "tamarind_pods": "fruit", "quince": "fruit", "prickly_pear": "fruit", "red_grapes": "fruit", "green_grapes": "fruit", "bartlett_pears": "fruit", "anjou_pears": "fruit", "bosc_pears": "fruit",
    "hass_avocados": "plant_fat", "young_coconut": "plant_fat", "mature_coconut_meat": "plant_fat", "olives": "plant_fat",
    "roma_tomatoes": "vegetable", "beefsteak_tomatoes": "vegetable", "cherry_tomatoes": "vegetable", "grape_tomatoes": "vegetable", "heirloom_tomatoes": "vegetable", "curly_kale": "vegetable", "lacinato_kale": "vegetable", "mustard_greens": "vegetable", "dandelion_greens": "vegetable", "beet_greens": "vegetable", "moringa_leaves": "vegetable", "romaine_lettuce": "vegetable", "iceberg_lettuce": "vegetable", "butter_lettuce": "vegetable", "green_leaf_lettuce": "vegetable", "red_leaf_lettuce": "vegetable", "bok_choy": "vegetable", "green_cabbage": "vegetable", "red_cabbage": "vegetable", "napa_cabbage": "vegetable", "savoy_cabbage": "vegetable", "red_beets": "vegetable", "golden_beets": "vegetable", "turnips": "vegetable", "daikon_radish": "vegetable", "burdock_root": "vegetable", "yellow_onions": "vegetable", "red_onions": "vegetable", "white_onions": "vegetable", "sweet_onions": "vegetable", "green_onions_scallions": "vegetable", "shallots": "vegetable", "leeks": "vegetable", "yellow_squash": "vegetable", "spaghetti_squash": "vegetable", "green_bell_peppers": "vegetable", "red_bell_peppers": "vegetable", "yellow_bell_peppers": "vegetable", "orange_bell_peppers": "vegetable", "jalapenos": "vegetable", "green_beans": "vegetable", "okra": "vegetable", "bitter_melon": "vegetable", "jicama": "vegetable", "chayote": "vegetable", "tomatillo": "vegetable", "nopales_cactus_pads": "vegetable", "radicchio": "vegetable", "endive": "vegetable", "white_button_mushrooms": "vegetable", "cremini_mushrooms": "vegetable", "portobello_mushrooms": "vegetable", "shiitake_mushrooms": "vegetable", "oyster_mushrooms": "vegetable", "maitake_mushrooms": "vegetable", "artichokes": "vegetable", "fennel": "vegetable", "nori": "vegetable", "wakame": "vegetable", "kombu": "vegetable", "dulse": "vegetable", "kelp": "vegetable", "sea_moss": "vegetable",
    "russet_potatoes": "starchy_veg", "yukon_gold_potatoes": "starchy_veg", "red_potatoes": "starchy_veg", "fingerling_potatoes": "starchy_veg", "orange_sweet_potatoes": "starchy_veg", "japanese_sweet_potatoes": "starchy_veg", "parsnips": "starchy_veg", "acorn_squash": "starchy_veg", "lotus_root": "starchy_veg", "taro": "starchy_veg", "yuca_cassava": "starchy_veg", "corn": "starchy_veg",
    "horseradish_root": "herb_spice",
    "jasmine_rice": "grain", "basmati_rice": "grain", "white_quinoa": "grain", "red_quinoa": "grain", "black_quinoa": "grain", "rolled_oats": "grain", "steel_cut_oats": "grain", "oat_groats": "grain", "finger_millet_ragi": "grain", "pearl_millet": "grain", "foxtail_millet": "grain", "bulgur_wheat": "grain", "popcorn_kernels": "grain", "wheat_berries": "grain", "sorghum": "grain",
    "cannellini_beans": "legume", "adzuki_beans": "legume", "mung_beans": "legume", "brown_lentils": "legume", "green_lentils": "legume", "red_lentils": "legume", "french_lentils_puy_lentils": "legume", "black_lentils_beluga_lentils": "legume", "green_split_peas": "legume", "yellow_split_peas": "legume", "lima_beans": "legume", "black_eyed_peas": "legume", "tempeh": "legume",
    "macadamia_nuts": "nut_seed", "cacao_nibs": "nut_seed",
    "whole_chicken": "poultry", "chicken_breast_boneless_skinless": "poultry", "chicken_breast_bone_in": "poultry", "chicken_thighs_boneless": "poultry", "chicken_thighs_bone_in": "poultry", "chicken_drumsticks": "poultry", "chicken_wings": "poultry", "chicken_tenderloins": "poultry", "chicken_quarters": "poultry", "ground_chicken": "poultry", "whole_turkey": "poultry", "turkey_breast": "poultry", "turkey_thighs": "poultry", "turkey_drumsticks": "poultry", "turkey_wings": "poultry", "ground_turkey": "poultry", "duck_whole": "poultry", "duck_breast": "poultry",
    "chicken_liver": "organ_meat", "chicken_heart": "organ_meat", "chicken_gizzards": "organ_meat", "chicken_feet": "organ_meat", "beef_kidney": "organ_meat", "beef_tongue": "organ_meat",
    "ground_beef_80_20": "red_meat", "ground_beef_90_10": "red_meat", "ground_chuck": "red_meat", "ribeye_steak": "red_meat", "new_york_strip_steak": "red_meat", "filet_mignon": "red_meat", "t_bone_steak": "red_meat", "porterhouse_steak": "red_meat", "sirloin_steak": "red_meat", "flat_iron_steak": "red_meat", "flank_steak": "red_meat", "skirt_steak": "red_meat", "hanger_steak": "red_meat", "chuck_roast": "red_meat", "brisket": "red_meat", "short_ribs": "red_meat", "beef_stew_meat": "red_meat", "top_round": "red_meat", "bottom_round": "red_meat", "eye_of_round": "red_meat", "tri_tip": "red_meat", "beef_shank": "red_meat", "oxtail": "red_meat", "lamb_chops": "red_meat", "rack_of_lamb": "red_meat", "leg_of_lamb": "red_meat", "lamb_shoulder": "red_meat", "ground_lamb": "red_meat", "pork_chops": "red_meat", "pork_loin": "red_meat", "pork_tenderloin": "red_meat", "pork_shoulder": "red_meat", "boston_butt": "red_meat", "picnic_shoulder": "red_meat", "ground_pork": "red_meat", "baby_back_ribs": "red_meat", "spare_ribs": "red_meat", "pork_belly": "red_meat", "pork_hocks": "red_meat",
    "herring": "fish_seafood", "anchovies": "fish_seafood", "trout": "fish_seafood", "cod": "fish_seafood", "halibut": "fish_seafood", "tilapia": "fish_seafood", "catfish": "fish_seafood", "tuna": "fish_seafood", "shrimp": "fish_seafood", "mussels": "fish_seafood", "clams": "fish_seafood",
    "duck_eggs": "egg",
    "whole_milk": "dairy", "cottage_cheese": "dairy", "plain_greek_yogurt": "dairy", "butter": "dairy",
}

CATEGORIES: tuple[str, ...] = tuple(sorted(set(FOOD_CATEGORY.values())))

# ------------------------------------------------------------------ broad groups
# The 16 FOOD_CATEGORY values are precise (diet-exclusion needs organ_meat separate from
# red_meat, starchy_veg separate from vegetable) but too fine-grained for a human browsing
# filter — nobody thinks "let me look at organ_meat" while shopping. BROAD_GROUP collapses
# them into the everyday groups people actually reach for: Meats, Seafood, Fruits, Vegetables,
# Grains, Legumes & Beans, Nuts & Seeds, Dairy & Eggs, Fats/Herbs/Condiments.
_CATEGORY_TO_BROAD_GROUP: dict[str, str] = {
    "red_meat": "Meats", "poultry": "Meats", "organ_meat": "Meats",
    "fish_seafood": "Seafood",
    "fruit": "Fruits",
    "vegetable": "Vegetables", "starchy_veg": "Vegetables",
    "grain": "Grains",
    "legume": "Legumes & Beans",
    "nut_seed": "Nuts & Seeds",
    "dairy": "Dairy & Eggs", "egg": "Dairy & Eggs",
    "plant_fat": "Fats, Herbs & Condiments", "herb_spice": "Fats, Herbs & Condiments",
    "sweetener": "Fats, Herbs & Condiments", "fermented": "Fats, Herbs & Condiments",
}
BROAD_GROUPS: tuple[str, ...] = tuple(dict.fromkeys(_CATEGORY_TO_BROAD_GROUP.values()))
FOOD_BROAD_GROUP: dict[str, str] = {
    food_id: _CATEGORY_TO_BROAD_GROUP[category] for food_id, category in FOOD_CATEGORY.items()
}

# ------------------------------------------------------------------ presets
# name -> (label, excluded categories). "whole_food" excludes nothing — it's your existing
# baseline (matches "eats mostly whole foods, no restrictions except no seed oils").
DIET_PRESETS: dict[str, dict[str, Any]] = {
    "whole_food": dict(label="Whole-food / no restrictions", excludes=set()),
    "vegetarian": dict(label="Vegetarian",
        excludes={"red_meat", "poultry", "organ_meat", "fish_seafood"}),
    "vegan": dict(label="Vegan",
        excludes={"red_meat", "poultry", "organ_meat", "fish_seafood", "egg", "dairy", "sweetener"}),
        # sweetener excluded because honey is the only sweetener-category food; dark chocolate
        # (also tagged sweetener) is plant-based, so vegan users can re-include it as a custom
        # override via candidate_manager.py edit if they want — the preset stays conservative.
    "pescatarian": dict(label="Pescatarian",
        excludes={"red_meat", "poultry", "organ_meat"}),
    "keto": dict(label="Keto / very low-carb",
        excludes={"grain", "legume", "starchy_veg", "sweetener", "fruit"}),
    "paleo": dict(label="Paleo",
        excludes={"grain", "legume", "dairy", "sweetener"}),
    "carnivore": dict(label="Carnivore",
        excludes={"fruit", "vegetable", "starchy_veg", "grain", "legume", "nut_seed",
                  "herb_spice", "sweetener", "fermented", "plant_fat"}),
    "mediterranean": dict(label="Mediterranean (emphasis-based, no hard exclusions)", excludes=set()),
}

# ------------------------------------------------------------------ custom exclusion toggles
# name -> (label, excluded categories OR specific food ids). Stack any number on top of a preset.
EXCLUSION_TOGGLES: dict[str, dict[str, Any]] = {
    "no_dairy": dict(label="No dairy", excludes_categories={"dairy"}, excludes_ids=set()),
    "no_red_meat": dict(label="No red meat", excludes_categories={"red_meat"}, excludes_ids=set()),
    "no_pork": dict(label="No pork", excludes_categories=set(), excludes_ids={"pork"}),
    "no_shellfish": dict(label="No shellfish", excludes_categories=set(), excludes_ids={"oysters"}),
    "no_grains": dict(label="No grains", excludes_categories={"grain"}, excludes_ids=set()),
    "no_legumes": dict(label="No legumes", excludes_categories={"legume"}, excludes_ids=set()),
    "no_nuts": dict(label="No nuts/seeds", excludes_categories={"nut_seed"}, excludes_ids=set()),
    "no_added_sugar": dict(label="No added sugar/sweeteners", excludes_categories={"sweetener"}, excludes_ids=set()),
    "no_nightshades": dict(label="No nightshades",
        excludes_categories=set(), excludes_ids={"tomatoes", "bell_peppers", "eggplant", "potatoes"}),
    # already true for this user per profile.txt — offered as a real toggle for anyone.
    "no_seed_oils": dict(label="No seed oils", excludes_categories=set(), excludes_ids=set()),
}


def excluded_ids_for(diet: str, toggles: set[str]) -> set[str]:
    """Every food id excluded by this preset + these toggles, combined."""
    if diet not in DIET_PRESETS:
        raise ValueError(f"Unknown diet preset: {diet}. Known: {', '.join(DIET_PRESETS)}")
    excluded_categories = set(DIET_PRESETS[diet]["excludes"])
    excluded_ids: set[str] = set()
    for name in toggles:
        if name not in EXCLUSION_TOGGLES:
            raise ValueError(f"Unknown exclusion toggle: {name}. Known: {', '.join(EXCLUSION_TOGGLES)}")
        spec = EXCLUSION_TOGGLES[name]
        excluded_categories |= spec["excludes_categories"]
        excluded_ids |= spec["excludes_ids"]
    excluded_ids |= {food_id for food_id, cat in FOOD_CATEGORY.items() if cat in excluded_categories}
    return excluded_ids


def allowed_food_ids(diet: str, toggles: set[str] = frozenset()) -> set[str]:
    """Every catalog food id that survives this diet + these toggles."""
    excluded = excluded_ids_for(diet, toggles)
    return set(FOOD_CATEGORY) - excluded
