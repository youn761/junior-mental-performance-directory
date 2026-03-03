from flask import Flask, render_template, request, abort, Response
from datetime import datetime
from models import db, Provider
from slugify import slugify
import os, json


# ----------------------------
# Tag mapping helpers (seed + SEO)
# ----------------------------

SPORT_SYNONYMS = {
    "running": "endurance",
    "cross country": "endurance",
    "xc": "endurance",
    "track": "endurance",
    "distance running": "endurance",
}

KNOWN_SPORTS = {
    "golf", "baseball", "basketball", "football", "soccer", "hockey",
    "field hockey", "softball", "tennis", "gymnastics", "volleyball",
    "endurance", "dance", "figure skating", "cricket", "rugby",
    "combat", "boxing", "mma", "swimming", "track",
    "multi-sport", "multisport",
}

# These are “what problem are we trying to solve?”
KNOWN_PROBLEMS = {
    "anxiety", "performance anxiety", "perfectionism", "burnout", "recruiting",
    "recruiting stress", "injury recovery", "return from injury", "fear of failure",
    "identity", "mistakes", "handling mistakes", "slumps", "pressure",
    "depression", "mental health", "eating disorders", "red-s", "overtraining",
    "school sport balance", "family", "family dynamics", "coping skills",
    "body image", "confidence crashes", "nerves",
}

# These are “what do they help you build / skills / approach?”
KNOWN_EXPERTISE = {
    "confidence", "focus", "resilience", "motivation", "mindset", "leadership",
    "consistency", "mental toughness", "visualization", "mental skills",
    "performance routines", "team culture", "character development", "life skills",
    "parent guidance", "parent education", "well-being", "high-performance",
    "elite performance", "trauma-informed", "trauma", "mindfulness",
    "goal setting", "emotional regulation",
}

def _clean_token(t: str) -> str:
    t = (t or "").strip().lower()
    t = t.replace("–", "-").replace("-", "-")
    t = " ".join(t.split())
    return t

def split_csv_tags(tag_string: str):
    if not tag_string:
        return []
    parts = [p.strip() for p in tag_string.split(",")]
    return [p for p in parts if p]

def normalize_sport_token(t: str) -> str:
    t = _clean_token(t)
    if t in SPORT_SYNONYMS:
        return SPORT_SYNONYMS[t]
    if t == "multisport":
        return "multi-sport"
    return t

def guess_3_tags_from_focus(focus_tags: str, primary_sport: str = None):
    """
    Takes the old single 'focus_tags' blob and maps into:
      - sport_tags
      - problem_tags
      - expertise_tags

    This is intentionally conservative: unknowns go to expertise (unless clearly sport/problem).
    """
    raw = split_csv_tags(focus_tags)
    sport = []
    prob = []
    exp = []

    for token in raw:
        t = _clean_token(token)
        if not t:
            continue

        # normalize common sport synonyms
        t_norm_sport = normalize_sport_token(t)

        # sport detection (including "field hockey")
        if t_norm_sport in KNOWN_SPORTS:
            sport.append(t_norm_sport)
            continue

        # problem detection
        if t in KNOWN_PROBLEMS:
            prob.append(t)
            continue

        # expertise detection
        if t in KNOWN_EXPERTISE:
            exp.append(t)
            continue

        # a few heuristic catches
        if "injury" in t:
            prob.append("injury recovery")
        elif "anx" in t:
            prob.append("anxiety")
        elif "recruit" in t:
            prob.append("recruiting")
        else:
            exp.append(t)

    # If no sport tags were found, fall back to primary_sport or multi-sport
    ps = normalize_sport_token(primary_sport or "")
    if not sport:
        if ps and _clean_token(ps) not in {"", "none"}:
            # if they put "Multi-sport" with a weird hyphen, normalize it
            ps_clean = normalize_sport_token(ps)
            sport = [ps_clean] if ps_clean else ["multi-sport"]
        else:
            sport = ["multi-sport"]

    # de-dupe while preserving order
    def dedupe(items):
        seen = set()
        out = []
        for x in items:
            x = _clean_token(x)
            if not x:
                continue
            # normalize multi sport spelling
            if x == "multisport":
                x = "multi-sport"
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    sport = dedupe(sport)
    prob = dedupe(prob)
    exp = dedupe(exp)

    return (", ".join(sport), ", ".join(prob), ", ".join(exp))


# ----------------------------
# SQLite safety: add missing columns if DB existed before schema change
# ----------------------------

def ensure_provider_columns(app: Flask):
    """
    If Render is using a persistent sqlite DB that was created before the new columns,
    SQLAlchemy create_all() will NOT add columns. This guard adds them if missing.
    """
    with app.app_context():
        # only run if table exists
        try:
            res = db.session.execute(db.text("SELECT name FROM sqlite_master WHERE type='table' AND name='providers';")).fetchone()
            if not res:
                return
            cols = db.session.execute(db.text("PRAGMA table_info(providers);")).fetchall()
            existing = {c[1] for c in cols}

            # Add new columns if missing
            if "sport_tags" not in existing:
                db.session.execute(db.text("ALTER TABLE providers ADD COLUMN sport_tags VARCHAR(512);"))
            if "problem_tags" not in existing:
                db.session.execute(db.text("ALTER TABLE providers ADD COLUMN problem_tags VARCHAR(512);"))
            if "expertise_tags" not in existing:
                db.session.execute(db.text("ALTER TABLE providers ADD COLUMN expertise_tags VARCHAR(512);"))

            # (Optional) keep focus_tags if it exists from old builds; we just ignore it now.
            db.session.commit()
        except Exception as e:
            # Don't hard-fail deploy because of a harmless migration attempt
            print(f"[warn] ensure_provider_columns skipped: {e}")


# ----------------------------
# App factory
# ----------------------------

def create_app():
    app = Flask(__name__)

    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///directory.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()

    # Ensure new columns exist if DB pre-dates your schema change
    ensure_provider_columns(app)

    # Seed DB if empty (supports either new 3-tag JSON OR old focus_tags JSON)
    with app.app_context():
        if Provider.query.count() == 0:
            seed_path = os.path.join(os.path.dirname(__file__), "providers_seed.json")
            if os.path.exists(seed_path):
                with open(seed_path, "r", encoding="utf-8") as f:
                    seed = json.load(f)

                for row in seed:
                    # Backward compatible: if the JSON still uses focus_tags, derive the 3 tag fields
                    sport_tags = row.get("sport_tags")
                    problem_tags = row.get("problem_tags")
                    expertise_tags = row.get("expertise_tags")

                    if not (sport_tags or problem_tags or expertise_tags):
                        st, pt, et = guess_3_tags_from_focus(
                            focus_tags=row.get("focus_tags", ""),
                            primary_sport=row.get("primary_sport", "")
                        )
                        row["sport_tags"] = st
                        row["problem_tags"] = pt
                        row["expertise_tags"] = et

                    # Create Provider using only fields your model accepts
                    allowed = {
                        "provider_name", "slug", "website_url", "primary_sport", "works_with_juniors",
                        "offers_remote", "city", "state", "short_description",
                        "sport_tags", "problem_tags", "expertise_tags"
                    }
                    clean_row = {k: v for k, v in row.items() if k in allowed}

                    db.session.add(Provider(**clean_row))

                db.session.commit()
                print(f"Seeded {len(seed)} providers from providers_seed.json")
            else:
                print("providers_seed.json not found; skipping seed")


    # ----------------------------
    # Routes
    # ----------------------------

    @app.route("/")
    def home():
        total = Provider.query.count()
        remote_count = Provider.query.filter_by(offers_remote=True).count()

        # "Golf-supporting" = has golf in sport_tags (even if primary_sport is multi-sport)
        golf_supporting = Provider.query.filter(Provider.sport_tags.ilike("%golf%")).count()

        return render_template(
            "home.html",
            total=total,
            remote_count=remote_count,
            golf_count=golf_supporting
        )

    @app.route("/coaches")
    def coaches():
        sport = (request.args.get("sport") or "").strip()
        remote = (request.args.get("remote") or "").strip()  # "1" => True filter
        problem = (request.args.get("problem") or "").strip()
        expertise = (request.args.get("expertise") or "").strip()

        # Backward compatibility: old "tag" param
        legacy_tag = (request.args.get("tag") or "").strip()
        if legacy_tag and not (problem or expertise):
            expertise = legacy_tag

        q = Provider.query

        # juniors-first
        q = q.filter_by(works_with_juniors=True)

        if sport:
            q = q.filter(Provider.sport_tags.ilike(f"%{sport}%"))

        if remote == "1":
            q = q.filter_by(offers_remote=True)

        if problem:
            q = q.filter(Provider.problem_tags.ilike(f"%{problem}%"))

        if expertise:
            q = q.filter(Provider.expertise_tags.ilike(f"%{expertise}%"))

        providers = q.order_by(Provider.provider_name.asc()).all()

        # Build filter options from DB
        def unique_sorted(items):
            return sorted(set([i for i in items if i]))

        all_providers = Provider.query.all()

        sport_opts = set()
        problem_opts = set()
        expertise_opts = set()
        for p in all_providers:
            for t in p.sport_tags_list():
                sport_opts.add(t)
            for t in p.problem_tags_list():
                problem_opts.add(t)
            for t in p.expertise_tags_list():
                expertise_opts.add(t)

        sports = unique_sorted(list(sport_opts))
        problems = unique_sorted(list(problem_opts))
        expertises = unique_sorted(list(expertise_opts))

        return render_template(
            "coaches.html",
            providers=providers,
            sports=sports,
            problems=problems,
            expertises=expertises,
            selected_sport=sport,
            selected_remote=(remote == "1"),
            selected_problem=problem,
            selected_expertise=expertise
        )

    @app.route("/coach/<slug>")
    def coach_detail(slug):
        p = Provider.query.filter_by(slug=slug).first()
        if not p:
            abort(404)
        return render_template("coach_detail.html", p=p)

    @app.route("/for-providers")
    def for_providers():
        return render_template("for_providers.html")


    # ----------------------------
    # SEO routes (3-category approach)
    # ----------------------------

    def providers_matching_slug(category: str, tag_slug: str):
        """
        Reliable match: compare slugify(tag) to tag_slug.
        This avoids messy SQL for hyphens/spaces and keeps URLs canonical.
        """
        all_providers = Provider.query.filter_by(works_with_juniors=True).all()
        matches = []

        for p in all_providers:
            if category == "sport":
                tags = p.sport_tags_list()
            elif category == "problem":
                tags = p.problem_tags_list()
            else:
                tags = p.expertise_tags_list()

            for t in tags:
                if slugify(t) == tag_slug:
                    matches.append(p)
                    break

        matches.sort(key=lambda x: (x.provider_name or "").lower())
        return matches

    def render_seo_tag_page(category: str, tag_slug: str):
        providers = providers_matching_slug(category, tag_slug)
        tag_text = tag_slug.replace("-", " ").strip()
        tag_title = tag_text.title()

        if category == "sport":
            page_title = f"Junior {tag_title} Mental Performance Coaches"
            h1 = f"Junior {tag_title} Mental Performance Coaches"
            canonical_url = f"/sport/{slugify(tag_text)}"
        elif category == "problem":
            page_title = f"{tag_title} Help for Junior Athletes | Mental Performance Coaches"
            h1 = f"Coaches Helping Junior Athletes With {tag_title}"
            canonical_url = f"/problem/{slugify(tag_text)}"
        else:
            page_title = f"{tag_title} Training for Junior Athletes | Mental Performance Coaches"
            h1 = f"{tag_title} Coaches for Junior Athletes"
            canonical_url = f"/expertise/{slugify(tag_text)}"

        # Reuse your existing seo template (you can keep seo_tag.html)
        return render_template(
            "seo_tag.html",
            providers=providers,
            total=len(providers),
            tag_title=tag_title,
            tag_text=tag_text,
            tag_slug=slugify(tag_text),
            page_title=page_title,
            h1=h1,
            canonical_url=canonical_url,
            category=category
        )

    @app.route("/sport/<sport_slug>")
    def seo_sport(sport_slug):
        return render_seo_tag_page("sport", sport_slug)

    @app.route("/problem/<problem_slug>")
    def seo_problem(problem_slug):
        return render_seo_tag_page("problem", problem_slug)

    @app.route("/expertise/<expertise_slug>")
    def seo_expertise(expertise_slug):
        return render_seo_tag_page("expertise", expertise_slug)


    # ----------------------------
    # Sitemap (core + coaches + 3 SEO families)
    # ----------------------------

    @app.route("/sitemap.xml")
    def sitemap():
        base_url = request.url_root.rstrip("/")
        today = datetime.utcnow().date().isoformat()

        urls = []

        core_paths = [
            "/",
            "/coaches",
            "/for-providers",
        ]

        for path in core_paths:
            urls.append({
                "loc": f"{base_url}{path}",
                "lastmod": today,
                "changefreq": "weekly",
                "priority": "0.8" if path == "/" else "0.6",
            })

        providers = Provider.query.order_by(Provider.provider_name.asc()).all()

        # Coach pages
        for p in providers:
            if p.slug:
                urls.append({
                    "loc": f"{base_url}/coach/{p.slug}",
                    "lastmod": today,
                    "changefreq": "monthly",
                    "priority": "0.7",
                })

        # SEO tag pages: collect unique slugs across all 3 categories
        sport_slugs = set()
        problem_slugs = set()
        expertise_slugs = set()

        for p in providers:
            for t in p.sport_tags_list():
                sport_slugs.add(slugify(t))
            for t in p.problem_tags_list():
                problem_slugs.add(slugify(t))
            for t in p.expertise_tags_list():
                expertise_slugs.add(slugify(t))

        for s in sorted(sport_slugs):
            urls.append({
                "loc": f"{base_url}/sport/{s}",
                "lastmod": today,
                "changefreq": "weekly",
                "priority": "0.6",
            })

        for s in sorted(problem_slugs):
            urls.append({
                "loc": f"{base_url}/problem/{s}",
                "lastmod": today,
                "changefreq": "weekly",
                "priority": "0.6",
            })

        for s in sorted(expertise_slugs):
            urls.append({
                "loc": f"{base_url}/expertise/{s}",
                "lastmod": today,
                "changefreq": "weekly",
                "priority": "0.6",
            })

        # XML render
        xml_items = []
        xml_items.append('<?xml version="1.0" encoding="UTF-8"?>')
        xml_items.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')

        for u in urls:
            xml_items.append("  <url>")
            xml_items.append(f"    <loc>{u['loc']}</loc>")
            xml_items.append(f"    <lastmod>{u['lastmod']}</lastmod>")
            xml_items.append(f"    <changefreq>{u['changefreq']}</changefreq>")
            xml_items.append(f"    <priority>{u['priority']}</priority>")
            xml_items.append("  </url>")

        xml_items.append("</urlset>")
        xml = "\n".join(xml_items)
        return Response(xml, mimetype="application/xml")

    return app


# Gunicorn / Render entrypoint
app = create_app()

if __name__ == "__main__":
    app.run(debug=True)