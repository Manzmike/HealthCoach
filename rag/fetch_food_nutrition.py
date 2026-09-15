#!/usr/bin/env python3
"""Fetch real USDA nutrition data (macros + core micronutrient panel) for every food in
supplement_audit.WHOLE_FOOD_CATALOG. Writes rag/food_nutrition.json.

Source: USDA FoodData Central (SR Legacy preferred — the classic generic reference data;
falls back to Foundation, then any type, if SR Legacy has no match). Every entry records
which real USDA fdcId it came from, so a value can always be traced back and verified —
nothing here is invented.

  cd ~/GitHub/HealthCoach/rag && source .venv/bin/activate
  source .env   # USDA_API_KEY
  python3 fetch_food_nutrition.py
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import supplement_audit as audit

HERE = Path(__file__).resolve().parent
OUT_PATH = HERE / "food_nutrition.json"
API_KEY = os.environ.get("USDA_API_KEY", "DEMO_KEY")
BASE = "https://api.nal.usda.gov/fdc/v1"

# Words that mean a hit is the WRONG form of the food (oil/processed/prepared) when the catalog
# item wants the plain raw/whole form. A hit containing any of these is skipped unless the
# food's own query override explicitly asks for that form (e.g. extra_virgin_olive_oil).
BAD_FORM_KEYWORDS = (
    "oil,", "souffle", "juice", "extract", "syrup", "candy", "cookie", "cake", "bread",
    "sauce", "soup", "chips", "flour", "powder", "concentrate", "baby food", "infant",
    "pastry", "pastelitos", "nectar", "paste", "beverage", "spread", "salad",
)

# Foods where a real, manually-verified USDA fdcId beats any search query — the automatic
# scorer kept losing these to a wrong-but-lexically-close product (a sprouted variant, a
# different species entirely, an unrelated blend). Verified by hand against USDA's own
# search UI before being hardcoded here; each is a real fdcId, not invented data.
FDC_ID_OVERRIDE: dict[str, int] = {
    "apples": 1750340,       # "Apples, fuji, with skin, raw" — plain "apples, raw" matched "Rose-apples", a different fruit
    "blueberries": 171711,   # "Blueberries, raw" — default query matched "Blueberries, frozen, sweetened"
    "pinto_beans": 175199,   # "Beans, pinto, mature seeds, raw" — default query ranked the sprouted variant first
    "kidney_beans": 173744,  # "Beans, kidney, red, mature seeds, raw" — default query ranked the sprouted variant first
    "farro": 169721,         # "Wheat, durum" — USDA has no distinct "farro" entry; closest real whole-wheat match
    "eggs": 171287,          # "Egg, whole, raw, fresh" — default query matched "egg white" only, and separately 404'd
    "plums": 169949,         # "Plums, raw" — display name "Plums / prunes" has a "/" that 400s the USDA search API
    "oysters": 175171,       # "Mollusks, oyster, eastern, wild, cooked, dry heat" — catalog explicitly wants cooked, not raw
    "daikon_radish": 168451, # "Radishes, oriental, raw" — USDA's actual term for daikon; default query matched radish seeds
    "black_eyed_peas": 169220,  # "Cowpeas (blackeyes), immature seeds, raw" — default query matched plain green peas
    "sea_moss": 168456,      # "Seaweed, irishmoss, raw" — sea moss = Irish moss, a real USDA synonym match
    "finger_millet_ragi": 169702,  # "Millet, raw" — USDA has no distinct finger millet/ragi entry; closest real match

    # ---- second expansion batch: the xlsx's vetted search terms are UK/international composition-
    # table vocabulary (CoFID/Ciqual/IFCT) and often don't match USDA's American naming at all —
    # "silverside"/"topside" (UK cuts) return nothing, "sweetcorn" misses USDA's "corn, sweet".
    # Each of these was re-verified by hand against USDA's own search for the American term.
    "jalapenos": 168576,      # "Peppers, jalapeno, raw" — plain display name matched correctly; V2's "chilli" term didn't
    "corn": 168538,           # "Corn, sweet, white, raw" — V2's "sweetcorn" term returned nothing
    "top_round": 169534,      # "Beef, round, top round, separable lean and fat, trimmed to 1/8\" fat, prime, raw"
    "bottom_round": 172128,   # "Beef, round, outside round, bottom round, steak, ... trimmed to 0\" fat, choice, raw"
    "ground_beef_90_10": 174030,  # "Beef, ground, 90% lean meat / 10% fat, raw" — exact match; V2's UK term 404'd
    "basmati_rice": 169756,   # "Rice, white, long-grain, regular, raw, unenriched" — USDA has no distinct basmati entry
    "golden_beets": 169145,   # "Beets, raw" — USDA doesn't distinguish beet color; same generic row as red beets
    "red_beets": 169145,      # "Beets, raw" — same generic row; USDA has no red-specific beet entry
    "plantains": 168215,      # "Plantains, green, raw" — locking in the correct match (V2's plain "plantain" term missed it)
    "filet_mignon": 173109,   # "Beef, New Zealand, imported, tenderloin, separable lean and fat, raw" — filet mignon is a tenderloin cut
    "cremini_mushrooms": 168434,  # "Mushrooms, brown, italian, or crimini, raw" — exact match
    "cranberries": 171722,    # "Cranberries, raw" — locking in the correct match
    "golden_berries": 173043, # "Groundcherries, (cape-gooseberries or poha), raw" — cape gooseberry is a real synonym for golden berry/Physalis peruviana
    "red_potatoes": 170029,   # "Potatoes, red, flesh and skin, raw" — exact match
    "russet_potatoes": 170027,  # "Potatoes, russet, flesh and skin, raw" — exact match
    "yukon_gold_potatoes": 170026,  # "Potatoes, flesh and skin, raw" — USDA has no Yukon-Gold-specific entry; closest generic
    "fingerling_potatoes": 170026,  # same generic potato row — USDA has no fingerling-specific entry
    "mustard_greens": 169256, # "Mustard greens, raw" — exact match; V2 term wrongly matched moringa/drumstick leaves
    "beet_greens": 170375,    # "Beet greens, raw" — exact match; V2 term wrongly matched moringa/drumstick leaves
    "nori": 168458,           # "Seaweed, laver, raw" — nori IS made from laver (Porphyra); this is the correct food, not a substitute
    "kombu": 168457,          # "Seaweed, kelp, raw" — kombu is a kelp (Saccharina japonica); USDA has no kombu-specific entry
    "whole_milk": 171265,     # "Milk, whole, 3.25% milkfat, with added vitamin D" — V2 term matched mozzarella cheese
    "olives": 169094,         # "Olives, ripe, canned (small-extra large)" — cured/canned IS the normal edible form; V2 term matched an unrelated pork deli loaf
    "cottage_cheese": 173417, # "Cheese, cottage, lowfat, 1% milkfat" — plain, not the "with vegetables" variant V2 matched
    "plain_greek_yogurt": 171304,  # "Yogurt, Greek, plain, whole milk" — plain, not the strawberry-flavored variant V2 matched
    "tuna": 175156,           # "Fish, tuna, fresh, skipjack, raw" — the most commonly eaten tuna species, raw; V2 term matched "tuna salad"
    "whole_chicken": 171447,  # "Chicken, broilers or fryers, meat and skin, raw" — a whole bird's meat+skin, not a single-part cut
    "turkey_breast": 171098,  # "Turkey, whole, breast, meat only, raw" — raw; V2 term matched pre-sliced deli meat
    "grapefruit": 174675,     # "Grapefruit, raw, pink and red, Florida" — SR Legacy has real energy data; the Foundation match didn't report Energy at all
    "beef_stew_meat": 2646174,  # "Beef, chuck, roast, boneless, choice, raw" — stew meat is cubed chuck; V2 term matched "Bologna, beef" (processed deli meat, wrong food entirely)
}

# Foods with NO honest USDA match at any specificity — every candidate the search API returns is
# a different food entirely (a candy bar, an unrelated fruit), not a reasonable substitute. Forcing
# these to NO MATCH is deliberate: better an honest gap than a wrong number presented as real data.
FORCE_NO_MATCH: frozenset[str] = frozenset({
    "cacao_nibs",  # every hit is a candy/chocolate product or cocoa powder — meaningfully different fat content, not raw nibs
})

# Catalog names that need a more specific/accurate USDA search query than their raw display name.
QUERY_OVERRIDE: dict[str, str] = {
    "avocado": "avocados, raw", "spinach": "spinach, raw", "oats": "oats",
    "beets": "beets, raw", "kimchi": "kimchi", "tamarind": "tamarind, raw",
    "honey_treats": "honey", "popcorn": "popcorn, air-popped", "cooked_mushrooms": "mushrooms, white, cooked",
    "mushrooms": "mushrooms, white, raw", "gelatin_broth": "bone broth", "coconut": "coconut meat, raw",
    "dark_chocolate": "dark chocolate, 70-85% cacao", "extra_virgin_olive_oil": "olive oil",
    "pasteurized_dairy": "milk, whole, 3.25% milkfat", "plain_yogurt": "yogurt, plain, whole milk",
    "kefir": "kefir, plain, low fat", "sauerkraut": "sauerkraut, canned",
    "lean_beef": "beef, top sirloin, lean, raw", "beef_liver": "beef, liver, raw",
    "beef_heart": "beef, heart, raw", "fish_eggs": "roe, mixed species, raw",
    "cinnamon_food": "cinnamon, ground", "turmeric_food": "turmeric, ground",
    "saffron_food": "saffron", "oregano": "oregano, dried", "ginger_food": "ginger root, raw",
    "garlic_food": "garlic, raw", "seaweed": "seaweed, kelp, raw",
    "green_peas": "peas, green, raw", "edamame": "edamame, frozen, prepared",
    "brown_rice": "rice, brown, long-grain, raw", "wild_rice": "wild rice, raw",
    "farro": "wheat, whole-grain", "gelatin": "gelatin, dry powder",
    "chicken": "chicken, broiler or fryers, breast, skinless, boneless, meat only, raw",
    "turkey": "turkey, breast, meat only, raw", "lamb": "lamb, loin, raw", "pork": "pork, loin, raw",
    "salmon": "salmon, atlantic, wild, raw", "sardines": "sardine, atlantic, canned in oil, drained",
    "mackerel": "mackerel, atlantic, raw", "oysters": "oysters, eastern, wild, raw",
    "butternut_squash": "squash, butternut, raw", "pumpkin": "pumpkin, raw",
    "sweet_potatoes": "sweet potato, raw", "bell_peppers": "peppers, sweet, red, raw",
    "collard_greens": "collards, raw", "swiss_chard": "swiss chard, raw",
    "brussels_sprouts": "brussels sprouts, raw",
}

# USDA nutrient name -> our clean field name + expected unit (for a sanity check, not enforced).
NUTRIENT_MAP: dict[str, str] = {
    "Energy": "energy_kcal",
    # USDA "Foundation" records (as opposed to SR Legacy) report energy under these names
    # instead of plain "Energy" — General Factors is the standard/widely-used calculation,
    # matching what SR Legacy's simple "Energy" field represents.
    "Energy (Atwater General Factors)": "energy_kcal",
    "Energy (Atwater Specific Factors)": "energy_kcal",
    "Protein": "protein_g",
    "Total lipid (fat)": "fat_g",
    "Carbohydrate, by difference": "carbs_g",
    "Fiber, total dietary": "fiber_g",
    "Sugars, total including NLEA": "sugar_g",
    "Sugars, total": "sugar_g",
    "Fatty acids, total saturated": "saturated_fat_g",
    "Cholesterol": "cholesterol_mg",
    "Calcium, Ca": "calcium_mg",
    "Iron, Fe": "iron_mg",
    "Magnesium, Mg": "magnesium_mg",
    "Phosphorus, P": "phosphorus_mg",
    "Potassium, K": "potassium_mg",
    "Sodium, Na": "sodium_mg",
    "Zinc, Zn": "zinc_mg",
    "Copper, Cu": "copper_mg",
    "Manganese, Mn": "manganese_mg",
    "Selenium, Se": "selenium_ug",
    "Vitamin C, total ascorbic acid": "vitamin_c_mg",
    "Thiamin": "thiamin_b1_mg",
    "Riboflavin": "riboflavin_b2_mg",
    "Niacin": "niacin_b3_mg",
    "Vitamin B-6": "vitamin_b6_mg",
    "Folate, total": "folate_ug",
    "Vitamin B-12": "vitamin_b12_ug",
    "Vitamin A, RAE": "vitamin_a_ug",
    "Vitamin E (alpha-tocopherol)": "vitamin_e_mg",
    "Vitamin D (D2 + D3)": "vitamin_d_ug",
    "Vitamin K (phylloquinone)": "vitamin_k_ug",
    "Choline, total": "choline_mg",
}


def _get(url: str, retries: int = 5) -> dict:
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < retries - 1:
                wait = 2 ** attempt  # 1, 2, 4, 8, 16s
                print(f"  429 rate-limited, backing off {wait}s...", end=" ", flush=True)
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("unreachable")


def _sanitize_query(query: str) -> str:
    """A literal "/" (e.g. "Ground beef 80/20", "Yuca / cassava") 400s the USDA search API
    outright — not a rate limit, not a no-match, the whole request is rejected. Replace it with
    a space rather than special-casing every affected catalog entry."""
    return query.replace("/", " ")


def search(query: str, data_type: str | None) -> list[dict]:
    query = _sanitize_query(query)
    params = {"query": query, "pageSize": 10, "api_key": API_KEY}
    if data_type:
        params["dataType"] = data_type
    url = f"{BASE}/foods/search?{urllib.parse.urlencode(params)}"
    time.sleep(0.3)  # pace every call, not just the outer loop — the 429 was a burst limit
    return _get(url).get("foods", [])


STOPWORDS = {"and", "or", "the", "raw", "of", "with", "in", "total", "cooking"}


def _is_bad_form(description: str, wants_processed_form: bool) -> bool:
    if wants_processed_form:
        return False
    lowered = description.lower()
    return any(bad in lowered for bad in BAD_FORM_KEYWORDS)


def _query_words(query: str) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", query.lower()) if w not in STOPWORDS and len(w) >= 3]


def _score(query_words: list[str], description: str, wants_processed_form: bool) -> tuple[int, int, int]:
    lowered = description.lower()
    # Whole-word matching only — a substring check let "wheat" match inside "buckwheat" and
    # send "farro" to a buckwheat product. desc_words is the description's own word set, so
    # both sides of the comparison are tokenized the same way.
    desc_words = {w for w in re.findall(r"[a-z]+", lowered) if w not in STOPWORDS and len(w) >= 3}
    query_word_set = set(query_words)
    overlap = sum(1 for w in query_words if w in desc_words)
    # Penalize extra unrelated significant words — "Oil, olive, salad or cooking" should beat
    # "Oil, corn, peanut, and olive" for query "olive oil": both match "oil"+"olive", but the
    # corn/peanut blend has more non-matching words diluting the match.
    extra = len(desc_words) - sum(1 for w in desc_words if w in query_word_set)
    raw_bonus = 1 if (not wants_processed_form and "raw" in lowered) else 0
    return (overlap, -extra, raw_bonus)


def _lookup_by_id(fdc_id: int) -> dict:
    detail = _get(f"{BASE}/food/{fdc_id}?api_key={API_KEY}")
    return {"fdcId": fdc_id, "description": detail["description"], "dataType": detail.get("dataType")}



# Vetted official search terms from the user-supplied source spreadsheet
# (whole_foods_item_sources.xlsx: UK CoFID / ANSES Ciqual / India IFCT / Frida / WAFCT search
# strings), covering the ~230-item catalog expansion. These take priority over QUERY_OVERRIDE
# for the same key since they're independently vetted, not a guess.
QUERY_OVERRIDE_V2: dict[str, str] = {
    "shallots": "shallot",
    "red_potatoes": "potato",
    "green_cabbage": "cabbage",
    "corn": "sweetcorn",
    "halibut": "halibut",
    "sweet_onions": "onion",
    "chicken_thighs_bone_in": "chicken thigh raw",
    "dandelion_greens": "dandelion",
    "red_grapes": "grape red",
    "pork_chops": "pork chop",
    "red_onions": "red onion",
    "red_beets": "beetroot",
    "bulgur_wheat": "bulgur",
    "portobello_mushrooms": "portobello",
    "turnips": "turnip",
    "plantains": "plantain raw",
    "elderberries": "elderberry",
    "lychee": "lychee",
    "yellow_squash": "summer squash",
    "beef_kidney": "kidney",
    "leg_of_lamb": "lamb leg",
    "filet_mignon": "beef fillet",
    "short_ribs": "short rib",
    "mature_coconut_meat": "coconut pulp",
    "ribeye_steak": "ribeye",
    "lima_beans": "lima",
    "brown_lentils": "lentil",
    "nectarines": "nectarine",
    "finger_millet_ragi": "finger millet",
    "herring": "herring",
    "bitter_melon": "bitter gourd",
    "beef_stew_meat": "beef stewing",
    "golden_berries": "physalis",
    "horseradish_root": "horseradish",
    "cannellini_beans": "cannellini",
    "green_lentils": "lentil green",
    "beef_shank": "shin",
    "green_bell_peppers": "green pepper",
    "black_eyed_peas": "black-eyed pea",
    "basmati_rice": "basmati",
    "apricots": "apricot",
    "fuji_apples": "apple eating raw",
    "soursop": "soursop",
    "tempeh": "tempeh",
    "rolled_oats": "oats rolled",
    "beef_tongue": "tongue",
    "chayote": "chayote",
    "cod": "cod",
    "dulse": "dulse",
    "turkey_wings": "turkey wing",
    "whole_milk": "whole milk",
    "mussels": "mussel",
    "kombu": "kombu",
    "hanger_steak": "hanger",
    "skirt_steak": "skirt",
    "yukon_gold_potatoes": "potato",
    "whole_turkey": "turkey whole raw",
    "lamb_chops": "lamb chop",
    "lotus_root": "lotus root",
    "fennel": "fennel",
    "flat_iron_steak": "top blade",
    "ground_turkey": "turkey mince",
    "lacinato_kale": "kale",
    "duck_breast": "duck breast",
    "turkey_thighs": "turkey thigh raw",
    "romaine_lettuce": "cos lettuce",
    "macadamia_nuts": "macadamia",
    "pork_tenderloin": "pork fillet",
    "persimmon": "persimmon",
    "acorn_squash": "winter squash",
    "spaghetti_squash": "spaghetti squash",
    "sea_moss": "Irish moss",
    "wakame": "wakame",
    "chicken_gizzards": "gizzard",
    "chicken_breast_boneless_skinless": "chicken breast raw skinless",
    "yellow_bell_peppers": "yellow pepper",
    "spare_ribs": "spare ribs",
    "porterhouse_steak": "porterhouse",
    "mulberries": "mulberry",
    "yellow_onions": "onion",
    "turkey_drumsticks": "turkey drumstick",
    "baby_back_ribs": "pork loin ribs",
    "passion_fruit": "passion fruit",
    "quince": "quince",
    "trout": "trout",
    "hass_avocados": "avocado",
    "jalapenos": "chilli",
    "oat_groats": "oat groats",
    "young_coconut": "coconut water",
    "granny_smith_apples": "apple eating raw",
    "mandarins": "mandarin",
    "ground_beef_90_10": "beef mince lean",
    "gala_apples": "apple eating raw",
    "green_leaf_lettuce": "lettuce leaf",
    "steel_cut_oats": "oats steel cut",
    "pink_lady_apples": "apple eating raw",
    "chicken_liver": "chicken liver",
    "pearl_millet": "pearl millet",
    "oxtail": "oxtail",
    "sirloin_steak": "sirloin",
    "cottage_cheese": "cottage cheese",
    "chicken_thighs_boneless": "chicken thigh raw",
    "french_lentils_puy_lentils": "Puy lentil",
    "goji_berries_unsweetened": "goji",
    "iceberg_lettuce": "iceberg lettuce",
    "savoy_cabbage": "savoy cabbage",
    "white_onions": "onion",
    "foxtail_millet": "foxtail millet",
    "sorghum": "sorghum",
    "chicken_drumsticks": "chicken drumstick raw",
    "brisket": "brisket",
    "chicken_feet": "chicken feet",
    "green_beans": "green beans",
    "burdock_root": "burdock",
    "napa_cabbage": "Chinese cabbage",
    "shrimp": "prawn shrimp",
    "pork_loin": "pork loin",
    "valencia_oranges": "orange raw",
    "whole_chicken": "chicken whole raw",
    "fingerling_potatoes": "potato",
    "red_lentils": "red lentil",
    "chuck_roast": "chuck",
    "bottom_round": "silverside",
    "lamb_shoulder": "lamb shoulder",
    "picnic_shoulder": "picnic",
    "t_bone_steak": "T-bone",
    "navel_oranges": "orange raw",
    "catfish": "catfish",
    "plain_greek_yogurt": "Greek yogurt",
    "curly_kale": "kale",
    "tri_tip": "tri-tip",
    "nopales_cactus_pads": "nopal",
    "cranberries": "cranberry",
    "eye_of_round": "eye of round",
    "okra": "okra",
    "green_onions_scallions": "spring onion",
    "olives": "olive",
    "artichokes": "globe artichoke",
    "endive": "endive",
    "adzuki_beans": "adzuki",
    "butter_lettuce": "butterhead",
    "honeycrisp_apples": "apple eating raw",
    "grape_tomatoes": "tomato",
    "pork_hocks": "hock",
    "amla_indian_gooseberry": "amla",
    "japanese_sweet_potatoes": "sweet potato white",
    "star_fruit": "carambola",
    "oyster_mushrooms": "oyster mushroom",
    "chicken_wings": "chicken wing raw",
    "white_quinoa": "quinoa",
    "yuca_cassava": "cassava",
    "shiitake_mushrooms": "shiitake",
    "mangoes": "mango",
    "russet_potatoes": "potato",
    "tomatillo": "tomatillo",
    "golden_beets": "beetroot",
    "cosmic_crisp_apples": "apple eating raw",
    "beet_greens": "beet leaves",
    "tamarind_pods": "tamarind",
    "maitake_mushrooms": "maitake",
    "green_split_peas": "split pea",
    "black_quinoa": "quinoa",
    "daikon_radish": "daikon",
    "anjou_pears": "pear",
    "popcorn_kernels": "popping corn",
    "wheat_berries": "wheat grain",
    "yellow_split_peas": "split pea yellow",
    "chicken_quarters": "chicken leg quarter",
    "ground_pork": "pork mince",
    "clams": "clam",
    "moringa_leaves": "moringa",
    "pork_belly": "pork belly",
    "black_lentils_beluga_lentils": "beluga",
    "beefsteak_tomatoes": "tomato",
    "ground_beef_80_20": "beef mince 20% fat",
    "duck_eggs": "duck egg",
    "bartlett_pears": "pear",
    "bosc_pears": "pear",
    "tuna": "tuna",
    "mustard_greens": "mustard leaves",
    "red_bell_peppers": "red pepper",
    "ground_chicken": "chicken mince",
    "blood_oranges": "blood orange",
    "chicken_breast_bone_in": "chicken breast raw with skin",
    "chicken_tenderloins": "chicken inner fillet",
    "ground_lamb": "lamb mince",
    "orange_bell_peppers": "pepper",
    "top_round": "topside",
    "clementines": "clementine",
    "honeydew_melon": "honeydew",
    "kelp": "kelp",
    "radicchio": "radicchio",
    "parsnips": "parsnip",
    "chicken_heart": "chicken heart",
    "jackfruit": "jackfruit",
    "jicama": "jicama",
    "orange_sweet_potatoes": "sweet potato",
    "flank_steak": "flank",
    "guava": "guava",
    "dragon_fruit": "pitaya",
    "leeks": "leek",
    "taro": "taro",
    "white_button_mushrooms": "mushroom",
    "cacao_nibs": "cocoa nibs",
    "turkey_breast": "turkey breast raw",
    "anchovies": "anchovy",
    "mung_beans": "mung",
    "heirloom_tomatoes": "tomato",
    "bok_choy": "pak choi",
    "duck_whole": "duck whole raw",
    "tilapia": "tilapia",
    "red_delicious_apples": "apple eating raw",
    "cantaloupe": "melon cantaloupe",
    "green_grapes": "grape green",
    "red_leaf_lettuce": "lettuce red",
    "prickly_pear": "prickly pear",
    "golden_delicious_apples": "apple eating raw",
    "boston_butt": "pork shoulder upper",
    "jasmine_rice": "white rice jasmine",
    "rack_of_lamb": "lamb rack",
    "red_quinoa": "quinoa",
    "cherry_tomatoes": "cherry tomato",
    "roma_tomatoes": "tomato",
    "new_york_strip_steak": "sirloin strip",
    "red_cabbage": "red cabbage",
    "pork_shoulder": "shoulder",
    "nori": "nori",
    "cremini_mushrooms": "brown mushroom",
    "ground_chuck": "beef mince from chuck",
    "butter": "butter",
}


def best_match(catalog_id: str, display_name: str) -> dict | None:
    if catalog_id in FORCE_NO_MATCH:
        return None
    if catalog_id in FDC_ID_OVERRIDE:
        return _lookup_by_id(FDC_ID_OVERRIDE[catalog_id])
    query = QUERY_OVERRIDE_V2.get(catalog_id) or QUERY_OVERRIDE.get(catalog_id, display_name)
    # If the override/query itself names a processed form (oil, honey, chocolate, ...), don't
    # filter those words out — that IS the food we want for this specific catalog entry.
    wants_processed_form = any(
        bad.rstrip(",") in query.lower() for bad in BAD_FORM_KEYWORDS
    )
    query_words = _query_words(query)

    # Pull SR Legacy + Foundation together into one pool before picking — searching them
    # sequentially and stopping at the first non-empty result set was the bug: SR Legacy often
    # returns *something* (e.g. "Oat bran, raw" for "oats") even when Foundation has the plainer,
    # more correct match ("Oats, whole grain, rolled") that we'd never see because we stopped early.
    pool: dict[int, dict] = {}
    for data_type in ("SR Legacy", "Foundation"):
        try:
            hits = search(query, data_type)
        except Exception as exc:
            print(f"  search error ({data_type}): {exc}")
            continue
        for h in hits:
            pool.setdefault(h["fdcId"], h)

    if not pool:
        try:
            hits = search(query, None)
        except Exception as exc:
            print(f"  search error (None): {exc}")
            hits = []
        # The unrestricted fallback can surface "Branded" consumer products (e.g. a specific
        # packaged "NORI" snack) when SR Legacy/Foundation have no generic entry at all. Branded
        # nutrition is formulation-specific and inconsistent — never a valid stand-in for generic
        # reference data, so exclude it here rather than let it silently win the pool.
        hits = [h for h in hits if h.get("dataType") != "Branded"]
        for h in hits:
            pool.setdefault(h["fdcId"], h)

    if not pool:
        return None

    candidates = list(pool.values())
    good_hits = [h for h in candidates if not _is_bad_form(h["description"], wants_processed_form)]
    candidates = good_hits or candidates  # if everything got filtered, fall back rather than fail

    # Score by real query-word overlap (not a blind "raw" substring check, which previously
    # matched foods like "Turkey, ...raw" for a "dark chocolate" query just because the word
    # "raw" happened to appear in the description). Ties keep the API's own relevance order.
    best = max(candidates, key=lambda h: _score(query_words, h["description"], wants_processed_form))
    return best


def fetch_nutrients(fdc_id: int) -> dict[str, float]:
    url = f"{BASE}/food/{fdc_id}?api_key={API_KEY}"
    detail = _get(url)
    out: dict[str, float] = {}
    for n in detail.get("foodNutrients", []):
        name = n.get("nutrient", {}).get("name")
        amount = n.get("amount")
        field = NUTRIENT_MAP.get(name)
        if field and amount is not None and field not in out:  # first hit wins (kcal before kJ dup etc.)
            out[field] = amount
    return out


def main() -> int:
    if API_KEY == "DEMO_KEY":
        print("WARNING: no USDA_API_KEY in environment — using DEMO_KEY (will rate-limit fast).")
    results: dict[str, dict] = {}
    if OUT_PATH.exists():
        results = json.loads(OUT_PATH.read_text())

    catalog = list(audit.WHOLE_FOOD_CATALOG)
    flagged: list[str] = []
    for i, c in enumerate(catalog, 1):
        if c.key in results:
            continue  # resumable — skip anything already fetched
        print(f"[{i}/{len(catalog)}] {c.key} ({c.name})...", end=" ", flush=True)
        match = best_match(c.key, c.name)
        if not match:
            print("NO MATCH FOUND")
            flagged.append(c.key)
            continue
        try:
            nutrients = fetch_nutrients(match["fdcId"])
        except Exception as exc:
            print(f"FETCH FAILED: {exc}")
            flagged.append(c.key)
            continue
        results[c.key] = {
            "display_name": c.name,
            "fdc_id": match["fdcId"],
            "usda_description": match["description"],
            "data_type": match.get("dataType"),
            "per_100g": nutrients,
        }
        print(f"-> fdcId {match['fdcId']} ({match['dataType']}) \"{match['description'][:50]}\" "
              f"[{len(nutrients)} nutrients]")
        OUT_PATH.write_text(json.dumps(results, indent=2))
        time.sleep(0.15)  # polite pacing, well within the real key's 1000/hr limit

    print(f"\nDone. {len(results)}/{len(catalog)} foods matched. Saved to {OUT_PATH}")
    if flagged:
        print(f"FLAGGED for manual review (no confident match): {', '.join(flagged)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
