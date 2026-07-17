import json
import pandas as pd
from slugify import slugify

YES_VALUES = {"y", "yes", "true", "1", "t"}

def to_bool(val, default=False):
    if val is None or pd.isna(val):
        return default
    s = str(val).strip().lower()
    if s == "":
        return default
    return s in YES_VALUES

def clean_str(val):
    """Convert a cell value to a stripped string, or None if blank/NaN.
    Guards against pandas NaN cells becoming the literal string 'nan'."""
    if val is None or pd.isna(val):
        return None
    s = str(val).strip()
    return s or None

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
        "photo filename": "photo_filename",
        "photo": "photo_filename",
        "photo_filename": "photo_filename",
        "phone": "phone",
        "phone number": "phone",
        "instagram": "instagram_url",
        "instagram url": "instagram_url",
        "facebook": "facebook_url",
        "facebook url": "facebook_url",
        "address": "street_address",
        "street address": "street_address",
    }

    new_cols = {}
    for c in df.columns:
        key = str(c).strip().lower()
        new_cols[c] = col_map.get(key, c)
    return df.rename(columns=new_cols)

def export_seed(excel_path: str, out_path: str = "providers_seed.json", sheet_name: str = "full table"):
    df = pd.read_excel(excel_path, sheet_name=sheet_name)
    df = normalize_columns(df)

    if "provider_name" not in df.columns:
        raise ValueError(f"Missing provider_name column. Found: {list(df.columns)}")

    # Build seed records (no DB access required)
    records = []
    used_slugs = set()
    skipped_invalid = 0

    for _, row in df.iterrows():
        name = clean_str(row.get("provider_name")) or ""
        if not name:
            continue

        # Skip providers not explicitly marked valid (blank = not yet vetted, excluded)
        if not to_bool(row.get("Valid_flag"), default=False):
            skipped_invalid += 1
            continue

        website_url = clean_str(row.get("website_url"))
        primary_sport = clean_str(row.get("primary_sport"))

        works_with_juniors = to_bool(row.get("works_with_juniors", "Y"), default=True)
        offers_remote = to_bool(row.get("offers_remote", "N"), default=False)

        city = clean_str(row.get("city"))
        state = clean_str(row.get("state"))
        short_description = clean_str(row.get("short_description"))
        focus_tags = clean_str(row.get("focus_tags"))
        photo_filename = clean_str(row.get("photo_filename"))
        phone = clean_str(row.get("phone"))
        instagram_url = clean_str(row.get("instagram_url"))
        facebook_url = clean_str(row.get("facebook_url"))
        street_address = clean_str(row.get("street_address"))

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
            "photo_filename": photo_filename,
            "phone": phone,
            "instagram_url": instagram_url,
            "facebook_url": facebook_url,
            "street_address": street_address,
        })

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"Exported {len(records)} records -> {out_path}")
    if skipped_invalid:
        print(f"Skipped {skipped_invalid} record(s) marked invalid (Valid_flag = No)")

if __name__ == "__main__":
    export_seed("listing_001.xlsx", "providers_seed.json", sheet_name="full table")