import json
import pandas as pd
from slugify import slugify

YES_VALUES = {"y", "yes", "true", "1", "t"}

def to_bool(val, default=False):
    if val is None:
        return default
    s = str(val).strip().lower()
    if s == "":
        return default
    return s in YES_VALUES

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    col_map = {
        "provider name": "provider_name",
        "name": "provider_name",
        "website": "website_url",
        "website url": "website_url",
        "url": "website_url",
        "primary sport": "primary_sport",
        "sport": "primary_sport",
        "works with juniors": "works_with_juniors",
        "juniors": "works_with_juniors",
        "junior": "works_with_juniors",
        "offers remote": "offers_remote",
        "remote": "offers_remote",
        "remote available": "offers_remote",
        "city": "city",
        "state": "state",
        "short description": "short_description",
        "description": "short_description",
        "focus tags": "focus_tags",
        "tags": "focus_tags",
        "focus areas": "focus_tags",
    }

    new_cols = {}
    for c in df.columns:
        key = str(c).strip().lower()
        new_cols[c] = col_map.get(key, c)
    return df.rename(columns=new_cols)

def export_seed(excel_path: str, out_path: str = "providers_seed.json"):
    df = pd.read_excel(excel_path)
    df = normalize_columns(df)

    if "provider_name" not in df.columns:
        raise ValueError(f"Missing provider_name column. Found: {list(df.columns)}")

    # Build seed records (no DB access required)
    records = []
    used_slugs = set()

    for _, row in df.iterrows():
        name = str(row.get("provider_name", "")).strip()
        if not name:
            continue

        website_url = str(row.get("website_url", "")).strip() or None
        primary_sport = str(row.get("primary_sport", "")).strip() or None

        works_with_juniors = to_bool(row.get("works_with_juniors", "Y"), default=True)
        offers_remote = to_bool(row.get("offers_remote", "N"), default=False)

        city = str(row.get("city", "")).strip() or None
        state = str(row.get("state", "")).strip() or None
        short_description = str(row.get("short_description", "")).strip() or None
        focus_tags = str(row.get("focus_tags", "")).strip() or None

        base_slug = slugify(name)
        slug = base_slug
        i = 2
        while slug in used_slugs:
            slug = f"{base_slug}-{i}"
            i += 1
        used_slugs.add(slug)

        records.append({
            "provider_name": name,
            "slug": slug,
            "website_url": website_url,
            "primary_sport": primary_sport,
            "works_with_juniors": works_with_juniors,
            "offers_remote": offers_remote,
            "city": city,
            "state": state,
            "short_description": short_description,
            "focus_tags": focus_tags,
        })

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"Exported {len(records)} records -> {out_path}")

if __name__ == "__main__":
    export_seed("listing 001.xlsx", "providers_seed.json")