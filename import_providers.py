import pandas as pd
from slugify import slugify
from app import create_app
from models import db, Provider

YES_VALUES = {"y", "yes", "true", "1", "t"}

def to_bool(val, default=False):
    if val is None:
        return default
    s = str(val).strip().lower()
    if s == "":
        return default
    return s in YES_VALUES

def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    # Map likely column names to our canonical names
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
        new_cols[c] = col_map.get(key, c)  # keep original if not mapped
    df = df.rename(columns=new_cols)
    return df

def unique_slug(base_slug: str) -> str:
    slug = base_slug
    i = 2
    while Provider.query.filter_by(slug=slug).first() is not None:
        slug = f"{base_slug}-{i}"
        i += 1
    return slug

def import_excel(path: str):
    df = pd.read_excel(path)
    df = normalize_columns(df)

    required = ["provider_name"]
    for r in required:
        if r not in df.columns:
            raise ValueError(f"Missing required column: {r}. Found columns: {list(df.columns)}")

    created = 0
    updated = 0

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

        # Use website URL as a soft unique key if present; else name
        existing = None
        if website_url:
            existing = Provider.query.filter_by(website_url=website_url).first()
        if not existing:
            existing = Provider.query.filter_by(provider_name=name).first()

        if existing:
            existing.provider_name = name
            existing.website_url = website_url
            existing.primary_sport = primary_sport
            existing.works_with_juniors = works_with_juniors
            existing.offers_remote = offers_remote
            existing.city = city
            existing.state = state
            existing.short_description = short_description
            existing.focus_tags = focus_tags
            updated += 1
        else:
            base_slug = slugify(name)
            slug = unique_slug(base_slug)

            p = Provider(
                provider_name=name,
                slug=slug,
                website_url=website_url,
                primary_sport=primary_sport,
                works_with_juniors=works_with_juniors,
                offers_remote=offers_remote,
                city=city,
                state=state,
                short_description=short_description,
                focus_tags=focus_tags,
            )
            db.session.add(p)
            created += 1

    db.session.commit()
    print(f"Import complete. Created={created}, Updated={updated}")

if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        # UPDATE THIS PATH to your file location if needed
        import_excel("listing 001.xlsx")
