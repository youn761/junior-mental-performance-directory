from flask import Flask, render_template, request, abort, Response
from datetime import datetime
from models import db, Provider
from slugify import slugify
import os, json
from sqlalchemy import or_


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
    "mental toughness", "visualization", "grit", "consistency", "pressure handling",
    "goal setting", "mindfulness", "team culture",
}


def normalize_tag(t: str) -> str:
    if not t:
        return ""
    t = t.strip().lower()
    t = SPORT_SYNONYMS.get(t, t)
    return t


def split_tags(s: str):
    if not s:
        return []
    parts = [p.strip() for p in str(s).replace(";", ",").split(",")]
    parts = [p for p in parts if p]
    # normalize + de-dupe
    seen = set()
    out = []
    for p in parts:
        n = normalize_tag(p)
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def guess_3_tags_from_focus(focus_tags: str, primary_sport: str):
    """
    Best-effort conversion when seed rows are still using legacy focus_tags.

    Returns: (sport_tags, problem_tags, expertise_tags) as comma-separated strings.
    """
    raw = split_tags(focus_tags)
    sport = set()
    prob = set()
    exp = set()

    # primary sport should count as sport tag too (when provided)
    ps = normalize_tag(primary_sport)
    if ps:
        sport.add(ps)

    for t in raw:
        # sport match
        if t in KNOWN_SPORTS:
            sport.add(t)
            continue

        # problem match
        if t in KNOWN_PROBLEMS:
            # normalize some common variants into canonical
            if t == "return from injury":
                t = "injury recovery"
            if t == "recruiting stress":
                t = "recruiting"
            prob.add(t)
            continue

        # expertise match
        if t in KNOWN_EXPERTISE:
            exp.add(t)
            continue

        # heuristics / fallbacks
        if "injury" in t:
            prob.add("injury recovery")
        elif "recruit" in t:
            prob.add("recruiting")
        elif "anx" in t or "nerv" in t or "pressure" in t:
            prob.add("anxiety")
        elif "focus" in t:
            exp.add("focus")
        elif "conf" in t:
            exp.add("confidence")
        elif "resil" in t:
            exp.add("resilience")
        elif "motiv" in t:
            exp.add("motivation")
        else:
            # if unknown, put it in expertise by default so it still shows up
            exp.add(t)

    def join(s):
        return ", ".join(sorted(s))

    return join(sport), join(prob), join(exp)


# ----------------------------
# App factory
# ----------------------------

def create_app():
    app = Flask(__name__)
    app.jinja_env.globals.update(slugify=slugify)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///directory.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    # ----------------------------
    # Lightweight migration helper: add new columns if missing
    # ----------------------------
    def ensure_provider_columns():
        # SQLite "ALTER TABLE ADD COLUMN" is safe if the column doesn't exist.
        # We'll check existing columns first.
        try:
            insp = db.inspect(db.engine)
            cols = {c["name"] for c in insp.get_columns("providers")}
        except Exception:
            return

        alters = []
        if "sport_tags" not in cols:
            alters.append("ALTER TABLE providers ADD COLUMN sport_tags VARCHAR(512)")
        if "problem_tags" not in cols:
            alters.append("ALTER TABLE providers ADD COLUMN problem_tags VARCHAR(512)")
        if "expertise_tags" not in cols:
            alters.append("ALTER TABLE providers ADD COLUMN expertise_tags VARCHAR(512)")

        if alters:
            with db.engine.begin() as conn:
                for sql in alters:
                    conn.exec_driver_sql(sql)

    with app.app_context():
        db.create_all()
        ensure_provider_columns()

        # Seed once if DB is empty
        if Provider.query.count() == 0:
            seed_path = os.path.join(os.path.dirname(__file__), "providers_seed.json")
            if os.path.exists(seed_path):
                with open(seed_path, "r", encoding="utf-8") as f:
                    seed = json.load(f)

                for row in seed:
                    # If the new tag fields are missing, try to derive them from focus_tags
                    if not row.get("sport_tags") and not row.get("problem_tags") and not row.get("expertise_tags"):
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
        # New 3-tag filters
        sport = (request.args.get("sport") or "").strip()
        problem = (request.args.get("problem") or "").strip()
        expertise = (request.args.get("expertise") or "").strip()
        remote = (request.args.get("remote") or "").strip()  # "1" => True filter

        # Backward compatibility: old single "tag" param from the UI (coaches.html)
        # Treat it as a generic tag filter across sport/problem/expertise.
        tag = (request.args.get("tag") or "").strip()

        q = Provider.query
        # juniors-first
        q = q.filter_by(works_with_juniors=True)

        if sport:
            q = q.filter(Provider.sport_tags.ilike(f"%{sport}%"))

        if remote == "1":
            q = q.filter_by(offers_remote=True)

        # If the legacy tag dropdown is used (and no specific 3-tag filter is selected),
        # match that tag across ALL 3 tag columns so the old UI still works.
        if tag and not (problem or expertise):
            q = q.filter(or_(
                Provider.sport_tags.ilike(f"%{tag}%"),
                Provider.problem_tags.ilike(f"%{tag}%"),
                Provider.expertise_tags.ilike(f"%{tag}%")
            ))
        else:
            if problem:
                q = q.filter(Provider.problem_tags.ilike(f"%{problem}%"))
            if expertise:
                q = q.filter(Provider.expertise_tags.ilike(f"%{expertise}%"))

        providers = q.order_by(Provider.provider_name.asc()).all()

        # Build filter options from DB (only juniors-first providers)
        def unique_sorted(items):
            return sorted(set([i for i in items if i]))

        all_providers = Provider.query.filter_by(works_with_juniors=True).all()

        # sport dropdown is driven by sport_tags (not primary_sport)
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

        # Legacy "Focus tag" dropdown: show the union of all tags so it remains useful
        tags = unique_sorted(list(problem_opts | expertise_opts | sport_opts))

        return render_template(
            "coaches.html",
            providers=providers,
            sports=sports,
            tags=tags,
            selected_sport=sport,
            selected_remote=(remote == "1"),
            selected_tag=tag,

            # keep these for future template upgrades (3 dropdowns)
            problems=problems,
            expertises=expertises,
            selected_problem=problem,
            selected_expertise=expertise,
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
            elif category == "expertise":
                tags = p.expertise_tags_list()
            else:
                tags = []

            for t in tags:
                if slugify(t) == tag_slug:
                    matches.append(p)
                    break

        return matches

    def tag_text_from_slug(slug: str) -> str:
        return slug.replace("-", " ").title()


    def providers_matching_combo(sport_slug: str = None, problem_slug: str = None, expertise_slug: str = None):
        all_providers = Provider.query.filter_by(works_with_juniors=True).all()
        matches = []

        for p in all_providers:
            sport_match = True
            if sport_slug:
                sport_match = any(slugify(t) == sport_slug for t in p.sport_tags_list())

            problem_match = True
            if problem_slug:
                problem_match = any(slugify(t) == problem_slug for t in p.problem_tags_list())

            expertise_match = True
            if expertise_slug:
                expertise_match = any(slugify(t) == expertise_slug for t in p.expertise_tags_list())

            if sport_match and problem_match and expertise_match:
                matches.append(p)

        return matches

    @app.route("/sport/<tag_slug>")
    def seo_sport(tag_slug):
        providers = providers_matching_slug("sport", tag_slug)
        tag_text = tag_slug.replace("-", " ").title()
        page_title = f"{tag_text} Mental Performance Coaches for Juniors"
        h1 = f"{tag_text} Mental Performance Coaches"
        return render_template(
            "seo_tag.html",
            providers=providers,
            page_title=page_title,
            h1=h1,
            tag_title=tag_text,
            tag_text=tag_text,
            category="sport",
        )

    @app.route("/problem/<tag_slug>")
    def seo_problem(tag_slug):
        providers = providers_matching_slug("problem", tag_slug)
        tag_text = tag_slug.replace("-", " ").title()
        page_title = f"{tag_text} Sports Psychology Support for Juniors"
        h1 = f"{tag_text} Sports Psychology Support"
        return render_template(
            "seo_tag.html",
            providers=providers,
            page_title=page_title,
            h1=h1,
            tag_title=tag_text,
            tag_text=tag_text,
            category="problem",
        )

    @app.route("/expertise/<tag_slug>")
    def seo_expertise(tag_slug):
        providers = providers_matching_slug("expertise", tag_slug)
        tag_text = tag_slug.replace("-", " ").title()
        page_title = f"{tag_text} Mental Skills Coaches for Juniors"
        h1 = f"{tag_text} Mental Skills Coaches"
        return render_template(
            "seo_tag.html",
            providers=providers,
            page_title=page_title,
            h1=h1,
            tag_title=tag_text,
            tag_text=tag_text,
            category="expertise",
        )

    @app.route("/sport/<sport_slug>/problem/<problem_slug>")
    def seo_sport_problem(sport_slug, problem_slug):
        providers = providers_matching_combo(sport_slug=sport_slug, problem_slug=problem_slug)

        sport_text = tag_text_from_slug(sport_slug)
        problem_text = tag_text_from_slug(problem_slug)

        page_title = f"{problem_text} Mental Performance Coaches for {sport_text} Athletes"
        h1 = f"{problem_text} Support for {sport_text} Athletes"

        return render_template(
            "seo_tag.html",
            providers=providers,
            page_title=page_title,
            h1=h1,
            tag_title=f"{problem_text} • {sport_text}",
            tag_text=f"{problem_text} for {sport_text}",
            category="problem",
        )


    @app.route("/sport/<sport_slug>/expertise/<expertise_slug>")
    def seo_sport_expertise(sport_slug, expertise_slug):
        providers = providers_matching_combo(sport_slug=sport_slug, expertise_slug=expertise_slug)

        sport_text = tag_text_from_slug(sport_slug)
        expertise_text = tag_text_from_slug(expertise_slug)

        page_title = f"{expertise_text} Coaches for {sport_text} Athletes"
        h1 = f"{expertise_text} Coaching for {sport_text} Athletes"

        return render_template(
            "seo_tag.html",
            providers=providers,
            page_title=page_title,
            h1=h1,
            tag_title=f"{expertise_text} • {sport_text}",
            tag_text=f"{expertise_text} for {sport_text}",
            category="expertise",
        )

    @app.route("/problem/<problem_slug>/expertise/<expertise_slug>")
    def seo_problem_expertise(problem_slug, expertise_slug):
        providers = providers_matching_combo(
            problem_slug=problem_slug,
            expertise_slug=expertise_slug
        )

        problem_text = tag_text_from_slug(problem_slug)
        expertise_text = tag_text_from_slug(expertise_slug)

        page_title = f"{expertise_text} Coaching for {problem_text}"
        h1 = f"{expertise_text} Coaching for {problem_text}"

        return render_template(
            "seo_tag.html",
            providers=providers,
            page_title=page_title,
            h1=h1,
            tag_title=f"{expertise_text} • {problem_text}",
            tag_text=f"{expertise_text} support for {problem_text}",
            category="expertise",
        )

    @app.route("/sitemap.xml")
    def sitemap():
        """
        Generate a simple XML sitemap with:
          - homepage
          - coaches listing
          - 3 tag-family SEO pages
        """
        base = request.url_root.rstrip("/")

        # Collect all tags from juniors-first providers
        all_providers = Provider.query.filter_by(works_with_juniors=True).all()
        sport_slugs = set()
        problem_slugs = set()
        expertise_slugs = set()

        for p in all_providers:
            for t in p.sport_tags_list():
                sport_slugs.add(slugify(t))
            for t in p.problem_tags_list():
                problem_slugs.add(slugify(t))
            for t in p.expertise_tags_list():
                expertise_slugs.add(slugify(t))

        urls = [
            f"{base}/",
            f"{base}/coaches",
        ]
        for s in sorted(sport_slugs):
            urls.append(f"{base}/sport/{s}")
        for p in sorted(problem_slugs):
            urls.append(f"{base}/problem/{p}")
        for e in sorted(expertise_slugs):
            urls.append(f"{base}/expertise/{e}")

        # combo pages
        combo_count = 0

        for s in sorted(sport_slugs):
            for p in sorted(problem_slugs):
                if providers_matching_combo(sport_slug=s, problem_slug=p):
                    urls.append(f"{base}/sport/{s}/problem/{p}")
                    combo_count += 1

            for e in sorted(expertise_slugs):
                if providers_matching_combo(sport_slug=s, expertise_slug=e):
                    urls.append(f"{base}/sport/{s}/expertise/{e}")
                    combo_count += 1

        for p in sorted(problem_slugs):
            for e in sorted(expertise_slugs):
                if providers_matching_combo(problem_slug=p, expertise_slug=e):
                    urls.append(f"{base}/problem/{p}/expertise/{e}")
                    combo_count += 1

        print(f"Sitemap base pages: {len(urls) - combo_count}")
        print(f"Sitemap combo pages: {combo_count}")
        print(f"Sitemap total urls: {len(urls)}")

        lastmod = datetime.utcnow().date().isoformat()

        xml = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for u in urls:
            xml.append("  <url>")
            xml.append(f"    <loc>{u}</loc>")
            xml.append(f"    <lastmod>{lastmod}</lastmod>")
            xml.append("  </url>")
        xml.append("</urlset>")

        return Response("\n".join(xml), mimetype="application/xml")

    return app


app = create_app()