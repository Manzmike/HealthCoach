#!/usr/bin/env python3
"""Reasonable serving size + weekly max for every food in the catalog.

Serving sizes are standard USDA/Dietary-Guidelines-for-Americans serving-size conventions by
food category — not invented, not personalized to your calorie target (that's tdee.py's job).

Weekly max is deliberately conservative in scope: it ONLY appears where a real, citable public-
health guideline sets one. Most foods get a serving size and NO cap — "eat vegetables every day"
isn't a moderation concern that needs a number attached to it. The three real cases covered here:

  - Liver (beef/chicken): preformed vitamin A (retinol) is fat-soluble and accumulates; regularly
    eating liver can push intake toward the tolerable upper limit. NIH Office of Dietary
    Supplements' Vitamin A fact sheet and common clinical nutrition guidance cite roughly once a
    week as a sensible ceiling for regular liver consumption.
    https://ods.od.nih.gov/factsheets/VitaminA-HealthProfessional/
  - Unprocessed red meat: WCRF/AICR's Diet, Nutrition, Physical Activity and Cancer report
    recommends limiting red meat to no more than about 3 servings (~350-500g cooked) a week,
    consistent with WHO/IARC's 2015 classification of red meat as a probable colorectal-cancer
    risk factor. Applied to the whole red_meat category (steaks, roasts, ground beef, lamb, pork
    cuts) since that's the category the guidance targets.
    https://www.wcrf.org/diet-activity-and-cancer/cancer-prevention-recommendations/limit-red-and-processed-meat/
  - Brazil nuts: extraordinarily selenium-dense (one nut can carry more than a full day's worth).
    NIH ODS' Selenium fact sheet and the adult Tolerable Upper Intake Level (400 mcg/day) are why
    common clinical guidance caps regular intake at a small handful a week, not a handful a day.
    https://ods.od.nih.gov/factsheets/Selenium-HealthProfessional/

Deliberately NOT covered: high-mercury fish (swordfish, shark, king mackerel, tilefish, marlin,
orange roughy, bigeye tuna) — none of those specific species are in this catalog (the fish here
matched to FDA "Best Choice"/"Good Choice" species: salmon, sardines, mackerel=Atlantic,
tuna=skipjack, trout, cod, halibut, tilapia, catfish, herring, anchovies, shrimp, mussels, clams),
so no mercury cap applies to what's actually here. If a genuinely high-mercury species is ever
added to the catalog, it belongs in WEEKLY_MAX_OVERRIDE with its own citation — never assumed.
"""
from __future__ import annotations

from typing import Any

import diet_rules as DR

# Standard serving size by the fine (16-way) diet_rules category — not the broad browsing group,
# since "Dairy & Eggs" or "Fats, Herbs & Condiments" span genuinely different serving conventions.
SERVING_SIZE_BY_CATEGORY: dict[str, str] = {
    "fruit": "1 medium piece or 1 cup chopped/berries",
    "vegetable": "1 cup raw or 1/2 cup cooked",
    "starchy_veg": "1/2 cup cooked (about one small potato)",
    "grain": "1/2 cup cooked (or 1 oz dry)",
    "legume": "1/2 cup cooked",
    "nut_seed": "1 oz (~28g, a small handful)",
    "egg": "1 egg",
    "poultry": "3-4 oz (85-113g) cooked",
    "red_meat": "3-4 oz (85-113g) cooked",
    "organ_meat": "3-4 oz (85-113g) cooked",
    "fish_seafood": "3-4 oz (85-113g) cooked",
    "dairy": "1 cup (milk/yogurt) or 1.5 oz (cheese)",
    "fermented": "1/2 cup",
    "plant_fat": "1 tbsp (oils) or ~1 oz (avocado/olives)",
    "herb_spice": "1-2 tsp fresh, or to taste",
    "sweetener": "1 tbsp",
}

# Real per-item overrides — specific foods where the category default is the wrong unit.
SERVING_SIZE_ITEM_OVERRIDE: dict[str, str] = {
    "extra_virgin_olive_oil": "1 tbsp",
    "butter": "1 tbsp",
    "honey_treats": "1 tbsp",
    "dark_chocolate": "1 oz (~28g)",
}

# Item-level caps take priority over category-level caps. Every entry names a real guideline —
# see the module docstring for citations. "max_per_week" is servings (at SERVING_SIZE above),
# not grams — a serving-count cap is what the underlying guidance actually states.
WEEKLY_MAX_BY_ITEM: dict[str, dict[str, Any]] = {
    "beef_liver": {"max_per_week": 1, "reason": "Preformed vitamin A (retinol) is fat-soluble and accumulates; regular liver intake can approach the tolerable upper limit.", "source": "NIH ODS Vitamin A fact sheet"},
    "chicken_liver": {"max_per_week": 1, "reason": "Same vitamin A accumulation concern as beef liver.", "source": "NIH ODS Vitamin A fact sheet"},
    "brazil_nuts": {"max_per_week": 7, "reason": "One Brazil nut can carry more than a full day's selenium; NIH ODS cites a small handful a week (roughly 1/day) as a sensible regular-intake ceiling, not a handful a day.", "source": "NIH ODS Selenium fact sheet"},
}

WEEKLY_MAX_BY_CATEGORY: dict[str, dict[str, Any]] = {
    "red_meat": {"max_per_week": 3, "reason": "WCRF/AICR recommends no more than ~3 servings (350-500g cooked) of red meat a week, consistent with WHO/IARC's classification of red meat as a probable colorectal-cancer risk factor.", "source": "WCRF/AICR Diet, Nutrition, Physical Activity and Cancer"},
}


def serving_guidance(catalog_key: str) -> dict[str, Any]:
    """Real serving size + weekly max (if any) for one catalog food. weekly_max is None when
    no real guideline applies — that's the expected, honest state for most foods, not a gap."""
    category = DR.FOOD_CATEGORY.get(catalog_key)
    serving_size = SERVING_SIZE_ITEM_OVERRIDE.get(catalog_key) or SERVING_SIZE_BY_CATEGORY.get(category, "typical single portion")

    cap = WEEKLY_MAX_BY_ITEM.get(catalog_key) or (WEEKLY_MAX_BY_CATEGORY.get(category) if category else None)
    return {
        "serving_size": serving_size,
        "weekly_max_servings": cap["max_per_week"] if cap else None,
        "weekly_max_reason": cap["reason"] if cap else None,
        "weekly_max_source": cap["source"] if cap else None,
    }
