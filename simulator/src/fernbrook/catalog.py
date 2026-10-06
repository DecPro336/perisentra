"""Fictional product catalog, stores and assortment, with the hidden parameters that drive their demand."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

NAMES: dict[str, list[str]] = {
    "Bakery": ["Sourdough Boule", "French Baguette", "Italian Bread", "Ciabatta Loaf", "Croissants 4 ct", "Bagels 6 ct",
               "Dinner Rolls 12 ct", "Multigrain Loaf", "Rye Bread", "Brioche Buns 8 ct", "Cinnamon Swirl Loaf",
               "Sandwich White Loaf", "Whole Wheat Loaf", "Kaiser Rolls 6 ct", "Garlic Bread", "Focaccia",
               "English Muffins 6 ct", "Pretzel Rolls 4 ct", "Hot Cross Buns 6 ct", "Hoagie Rolls 6 ct", "Challah",
               "Seeded Rye", "Mini Baguettes 4 ct", "King Cake"],
    "Produce": ["Strawberries 1 lb", "Bananas 3 lb", "Gala Apples 3 lb", "Avocados 4 ct", "Roma Tomatoes 1 lb",
                "Grape Tomatoes 1 pt", "Blueberries 1 pt", "Raspberries 6 oz", "Baby Carrots 1 lb", "Broccoli Crowns 1 lb",
                "Bell Peppers 3 ct", "English Cucumber", "Green Beans 12 oz", "Red Seedless Grapes 2 lb",
                "Clementines 3 lb", "Watermelon", "Sweet Corn 4 ct", "Peaches 2 lb", "Asparagus Bunch",
                "Honeycrisp Apples 3 lb", "Butternut Squash", "Lemons 2 lb", "Limes 2 lb", "White Mushrooms 8 oz",
                "Spinach Bunch", "Zucchini 1 lb", "Yellow Onions 3 lb", "Russet Potatoes 5 lb", "Pineapple",
                "Mango", "Cantaloupe", "Kiwi 1 lb"],
    "Salads & Fresh-Cut": ["Spring Mix 5 oz", "Romaine Hearts 3 ct", "Baby Spinach 5 oz", "Caesar Salad Kit",
                           "Chopped Salad Kit", "Iceberg Lettuce", "Arugula 5 oz", "Shredded Lettuce 8 oz",
                           "Coleslaw Mix 14 oz", "Cut Fruit Medley 16 oz", "Veggie Tray", "Kale Salad Kit",
                           "Broccoli Florets 12 oz", "Shredded Carrots 10 oz", "Pico de Gallo 16 oz", "Butter Lettuce",
                           "Cobb Salad Bowl", "Fresh Salsa 16 oz"],
    "Dairy": ["Whole Milk 1 gal", "2% Milk 1 gal", "Skim Milk Half Gal", "Organic Whole Milk Half Gal",
              "Greek Yogurt 32 oz", "Vanilla Yogurt 4 pk", "Strawberry Yogurt 4 pk", "Heavy Whipping Cream 1 pt",
              "Half & Half 1 qt", "Sour Cream 16 oz", "Cottage Cheese 16 oz", "Salted Butter 1 lb",
              "Unsalted Butter 1 lb", "Large Eggs 12 ct", "Cage-Free Eggs 12 ct", "Chocolate Milk Half Gal",
              "Kefir 32 oz", "Oat Milk Half Gal", "Almond Milk Half Gal", "Coffee Creamer 32 oz", "Cream Cheese 8 oz",
              "Rice Pudding 4 pk", "Chocolate Pudding 4 pk", "Eggnog 1 qt", "Buttermilk 1 qt", "Skyr 4 pk"],
    "Cheese": ["Sharp Cheddar Block 8 oz", "Shredded Mozzarella 16 oz", "Brie Wedge 8 oz", "Fresh Mozzarella 8 oz",
               "Goat Cheese Log 4 oz", "Parmesan Wedge 6 oz", "Swiss Slices 8 oz", "Pepper Jack Block 8 oz",
               "Feta Crumbles 6 oz", "Smoked Gouda 7 oz", "Blue Cheese Crumbles 5 oz", "Burrata 8 oz",
               "Havarti Slices 8 oz", "Colby Jack Block 8 oz", "Ricotta 15 oz", "Gruyere Wedge 6 oz",
               "String Cheese 12 ct", "Wisconsin Cheese Curds 12 oz"],
    "Meat": ["Ground Beef 80/20 1 lb", "Ground Beef 93/7 1 lb", "Boneless Chicken Breast 1.5 lb", "Chicken Thighs 2 lb",
             "Ribeye Steak", "NY Strip Steak", "Pork Chops 4 ct", "Baby Back Ribs", "Italian Sausage 1 lb",
             "Bratwurst 5 ct", "Whole Chicken", "Chicken Wings 2 lb", "Beef Stew Meat 1 lb", "Pork Tenderloin",
             "Ground Turkey 1 lb", "Fresh Whole Turkey", "Thick-Cut Bacon 12 oz", "Beef Hot Dogs 8 ct", "Flank Steak",
             "Beef Brisket"],
    "Seafood": ["Atlantic Salmon Fillet 1 lb", "Cod Fillets 1 lb", "Cooked Shrimp 1 lb", "Raw Shrimp 1 lb",
                "Tilapia Fillets 1 lb", "Smoked Salmon 4 oz", "Sea Scallops 12 oz", "Ahi Tuna Steaks",
                "Mahi Mahi Fillets", "Snow Crab Clusters", "Lake Trout Fillet", "Walleye Fillet", "Lobster Tails 2 ct"],
    "Prepared Foods": ["Rotisserie Chicken", "Mac & Cheese 16 oz", "Lasagna Family Size", "Chicken Pot Pie",
                       "Meatloaf Dinner", "Turkey Club Sandwich", "Chicken Caesar Wrap", "California Roll 8 pc",
                       "Potato Salad 16 oz", "Macaroni Salad 16 oz", "Chicken Noodle Soup 24 oz", "Beef Chili 24 oz",
                       "Fried Chicken 8 pc", "Fresh Margherita Pizza", "Mashed Potatoes 24 oz", "Pulled Pork 16 oz",
                       "Buffalo Chicken Dip", "Chicken Tenders 12 oz", "Hummus Snack Pack", "Fresh Pasta 9 oz",
                       "Burrito Bowl", "Butternut Squash Soup 24 oz"],
    "Deli Meats": ["Oven Roasted Turkey 8 oz", "Black Forest Ham 8 oz", "Genoa Salami 6 oz", "Roast Beef 8 oz",
                   "Pastrami 8 oz", "Pepperoni Slices 6 oz", "Honey Ham 8 oz", "Smoked Turkey 8 oz", "Prosciutto 3 oz",
                   "Bologna 12 oz", "Capicola 6 oz", "Corned Beef 8 oz", "Chicken Breast Slices 8 oz", "Summer Sausage",
                   "Liverwurst 8 oz", "Italian Combo Pack", "Hard Salami 6 oz"],
    "Pastries & Desserts": ["Apple Pie 9 in", "Pumpkin Pie 9 in", "Chocolate Chip Cookies 12 ct", "Glazed Donuts 6 ct",
                            "Blueberry Muffins 4 ct", "Cheesecake Slices 2 ct", "Cupcakes 6 ct", "Carrot Cake Slice",
                            "Fudge Brownies 6 ct", "Cinnamon Rolls 4 ct", "Fruit Tart", "Pecan Pie 9 in",
                            "Cream Puffs 6 ct", "Cheese Danish 4 ct", "Key Lime Pie", "Strawberry Shortcake",
                            "Holiday Cookie Tray"],
    "Fresh Juice": ["Orange Juice 52 oz", "Fresh Squeezed OJ 32 oz", "Apple Cider 64 oz", "Lemonade 52 oz",
                    "Green Juice 16 oz", "Grapefruit Juice 32 oz", "Strawberry Banana Smoothie 15 oz",
                    "Mango Smoothie 15 oz", "Carrot Ginger Juice 16 oz", "Cold Brew Coffee 32 oz", "Sweet Tea 52 oz",
                    "Watermelon Juice 16 oz", "Kombucha 16 oz"],
}

# Products that are only listed for part of the year (month windows), giving cold starts each season.
SEASONAL = {
    "King Cake": [1, 2],
    "Hot Cross Buns 6 ct": [3, 4],
    "Asparagus Bunch": [3, 4, 5],
    "Strawberry Shortcake": [5, 6, 7],
    "Watermelon": [6, 7, 8],
    "Sweet Corn 4 ct": [7, 8, 9],
    "Peaches 2 lb": [7, 8],
    "Cantaloupe": [5, 6, 7, 8, 9],
    "Watermelon Juice 16 oz": [6, 7, 8],
    "Honeycrisp Apples 3 lb": [9, 10, 11, 12],
    "Apple Cider 64 oz": [9, 10, 11],
    "Pumpkin Pie 9 in": [9, 10, 11, 12],
    "Butternut Squash": [9, 10, 11, 12, 1],
    "Butternut Squash Soup 24 oz": [10, 11, 12, 1, 2, 3],
    "Clementines 3 lb": [11, 12, 1, 2],
    "Fresh Whole Turkey": [11, 12],
    "Pecan Pie 9 in": [11, 12],
    "Eggnog 1 qt": [11, 12],
    "Holiday Cookie Tray": [12],
}

# Holiday peaks: (occasion, demand multiplier at the peak). Occasions are matched to real US holidays:
# "thanksgiving" (the days before Thanksgiving), "winter" (Christmas and New Year's Eve),
# "cookout" (Memorial Day, Independence Day, Labor Day weekends).
FESTIVE = {
    "Fresh Whole Turkey": ("thanksgiving", 6.0), "Pumpkin Pie 9 in": ("thanksgiving", 4.0),
    "Pecan Pie 9 in": ("thanksgiving", 3.0), "Dinner Rolls 12 ct": ("thanksgiving", 2.0),
    "Heavy Whipping Cream 1 pt": ("thanksgiving", 1.8), "Butternut Squash": ("thanksgiving", 1.8),
    "Russet Potatoes 5 lb": ("thanksgiving", 1.7), "Green Beans 12 oz": ("thanksgiving", 1.8),
    "Eggnog 1 qt": ("winter", 2.5), "Holiday Cookie Tray": ("winter", 3.0), "Lobster Tails 2 ct": ("winter", 3.0),
    "Cooked Shrimp 1 lb": ("winter", 2.2), "Sea Scallops 12 oz": ("winter", 2.0), "Ribeye Steak": ("winter", 1.6),
    "Brie Wedge 8 oz": ("winter", 1.8),
    "Baby Back Ribs": ("cookout", 2.4), "Bratwurst 5 ct": ("cookout", 2.4), "Beef Hot Dogs 8 ct": ("cookout", 2.6),
    "Ground Beef 80/20 1 lb": ("cookout", 1.8), "Sweet Corn 4 ct": ("cookout", 2.0), "Watermelon": ("cookout", 2.2),
    "Potato Salad 16 oz": ("cookout", 2.0), "Macaroni Salad 16 oz": ("cookout", 1.8), "Kaiser Rolls 6 ct": ("cookout", 1.8),
    "Coleslaw Mix 14 oz": ("cookout", 1.8), "Chicken Wings 2 lb": ("cookout", 1.6), "Lemonade 52 oz": ("cookout", 1.6),
}
HIGH_VOLUME = {"French Baguette", "Sandwich White Loaf", "Bananas 3 lb", "Whole Milk 1 gal", "Rotisserie Chicken"}

SUBFAMILY_KEYWORDS = {
    "Bakery": {"Sweet Bakery": ["Croissant", "Cinnamon", "Hot Cross", "King Cake", "Brioche", "Challah"],
               "Breads & Rolls": []},
    "Produce": {"Fruit": ["Strawberries", "Bananas", "Apples", "Avocados", "Blueberries", "Raspberries", "Grapes",
                          "Clementines", "Watermelon", "Peaches", "Lemons", "Limes", "Pineapple", "Mango",
                          "Cantaloupe", "Kiwi"], "Vegetables": []},
    "Dairy": {"Milk & Cream": ["Milk", "Whipping Cream", "Half & Half", "Creamer", "Buttermilk", "Eggnog", "Kefir"],
              "Eggs & Butter": ["Eggs", "Butter"], "Yogurt & Desserts": []},
    "Meat": {"Poultry": ["Chicken", "Turkey"], "Beef": ["Beef", "Steak", "Brisket", "Ribeye"], "Pork & Sausage": []},
    "Prepared Foods": {"Grab & Go": ["Sandwich", "Wrap", "Roll 8 pc", "Pizza", "Hummus", "Bowl"],
                       "Hot & Ready Meals": []},
}


@dataclass
class Catalog:
    stores: pd.DataFrame
    products: pd.DataFrame
    assortment: pd.DataFrame          # store_id, sku_id, listed_from, listed_to (empty: still listed)
    truth_products: pd.DataFrame      # hidden ground-truth parameters per SKU
    truth_stores: pd.DataFrame


def _subfamily(family: str, name: str) -> str:
    rules = SUBFAMILY_KEYWORDS.get(family)
    if not rules:
        return family
    for sub, keys in rules.items():
        if any(k in name for k in keys):
            return sub
    return list(rules)[-1]


def _upc_a(rng: np.random.Generator) -> str:
    """12-digit UPC-A with a valid check digit (number system 0, fictional manufacturer codes)."""
    digits = [0] + [int(d) for d in rng.integers(0, 10, 10)]
    checksum = (10 - (3 * sum(digits[0::2]) + sum(digits[1::2])) % 10) % 10
    return "".join(map(str, digits + [checksum]))


def _snap_price(p: float) -> float:
    for ending in (0.99, 0.49, 0.79, 0.29):
        candidate = np.floor(p) + ending
        if abs(candidate - p) < 0.45:
            return round(float(candidate), 2)
    return round(float(np.floor(p) + 0.99), 2)


def build_catalog(cfg: dict, rng: np.random.Generator) -> Catalog:
    fams: dict = cfg["families"]
    n_skus = int(cfg["world"]["n_skus"])
    start = date.fromisoformat(str(cfg["calendar"]["start_date"]))
    as_of = date.fromisoformat(str(cfg["calendar"]["catalog_reference_date"]))
    warmup = int(cfg["calendar"]["warmup_days"])

    # ---- products -------------------------------------------------------------------------------
    shares = np.array([f["share"] for f in fams.values()], dtype=float)
    counts = np.maximum(1, np.round(shares / shares.sum() * n_skus)).astype(int)
    counts[np.argmax(counts)] += n_skus - counts.sum()
    rows, truth = [], []
    sku_id = 1000
    for (family, fp), n in zip(fams.items(), counts):
        pool = list(NAMES[family])
        rng.shuffle(pool)
        seasonal_first = [n_ for n_ in NAMES[family] if n_ in SEASONAL]
        chosen = seasonal_first + [p for p in pool if p not in seasonal_first]
        chosen = (chosen * 3)[:n]
        seen: dict[str, int] = {}
        for name in chosen:
            seen[name] = seen.get(name, 0) + 1
            label = name if seen[name] == 1 else f"{name} {['Organic', 'Premium', 'Local'][min(seen[name] - 2, 2)]}"
            sku_id += 1
            lo, hi = fp["price"]
            price = _snap_price(float(np.exp(rng.uniform(np.log(lo), np.log(hi)))))
            if "Organic" in label or "Premium" in label:
                price = _snap_price(price * 1.25)
            shelf = int(rng.integers(fp["shelf"][0], fp["shelf"][1] + 1))
            tracked = bool(rng.random() < fp["expiry_tracked"])
            elasticity = float(np.clip(fp["elasticity"] + rng.normal(0, 0.28), 0.45, 3.4))
            base = float(fp["base"] * np.exp(rng.normal(0, 0.62)))
            if name in HIGH_VOLUME:
                base *= 4.5
            pack = int(rng.integers(fp["pack"][0], fp["pack"][1] + 1))
            # new launches in the last ~4 months (short history -> borrow strength from family/store)
            launch = start - timedelta(days=warmup + 400)
            if rng.random() < 0.05:
                launch = as_of - timedelta(days=int(rng.integers(25, 120)))
            rows.append({
                "sku_id": sku_id, "upc": _upc_a(rng), "name": label.strip(), "family": family,
                "subfamily": _subfamily(family, name), "regular_price": price,
                "unit_cost": round(price * fp["cost_ratio"] * float(np.exp(rng.normal(0, 0.06))), 3),
                "shelf_life_days": shelf, "expiry_tracked": tracked, "case_pack": pack,
                "launch_date": launch, "season_months": SEASONAL.get(name), "delivery": fp["delivery"],
            })
            truth.append({
                "sku_id": sku_id, "true_elasticity": elasticity, "base_demand": base,
                "dispersion_k": float(fp["k"]),
                "temp_sens": fp["temp"] * float(np.exp(rng.normal(0, 0.25))),
                "hot_sens": fp["hot"] * float(np.exp(rng.normal(0, 0.25))),
                "rain_sens": fp["rain"], "season_amp": fp["season_amp"] * float(np.exp(rng.normal(0, 0.3))),
                "season_phase": float(rng.normal(0, 0.35)),
                "festive_occasion": FESTIVE[name][0] if name in FESTIVE else "generic",
                "festive_mult": FESTIVE[name][1] if name in FESTIVE else 1.0 + max(0.0, rng.normal(0.12, 0.10)),
                "trend_per_year": float(rng.normal(0.0, 0.06)),
                "promo_boost": float(np.exp(rng.normal(0.12, 0.08))),
            })
    products = pd.DataFrame(rows)
    truth_products = pd.DataFrame(truth)

    # ---- stores ----------------------------------------------------------------------------------
    stores = pd.DataFrame(cfg["stores"])
    stores = stores.rename(columns={"id": "store_id"})
    stores["pos_code"] = stores["store_id"].map(lambda i: f"STORE-{i:03d}")
    fmt_cfg = cfg["formats"]
    stores["surface_sqft"] = stores["format"].map(lambda f: fmt_cfg[f]["surface_sqft"]) * np.exp(rng.normal(0, 0.15, len(stores)))
    stores["surface_sqft"] = stores["surface_sqft"].round(-2).astype(int)
    stores["summer_effect"] = stores["summer"].fillna(0.0) if "summer" in stores else 0.0
    stores["opened"] = [date(2008 + int(y), 3, 1) for y in rng.integers(0, 12, len(stores))]
    fmt = cfg["formats"]
    truth_stores = pd.DataFrame({
        "store_id": stores["store_id"],
        "store_scale": [fmt[f]["volume"] * float(np.exp(rng.normal(0, 0.18))) for f in stores["format"]],
        "footfall_base": [fmt[f]["footfall"] * float(np.exp(rng.normal(0, 0.12))) for f in stores["format"]],
        "sunday_factor": [fmt[f]["sunday"] for f in stores["format"]],
    })

    # ---- assortment ------------------------------------------------------------------------------
    assort = []
    for _, st in stores.iterrows():
        coverage = fmt[st["format"]]["assortment"]
        for _, pr in products.iterrows():
            # popular items are listed everywhere; small formats drop the tail
            keep = rng.random() < coverage or pr["regular_price"] < 2.5
            if not keep:
                continue
            assort.append({"store_id": st["store_id"], "sku_id": pr["sku_id"],
                           "listed_from": max(pr["launch_date"], start - timedelta(days=warmup)), "listed_to": None})
    assortment = pd.DataFrame(assort)
    return Catalog(stores, products, assortment, truth_products, truth_stores)
