from flask import Flask, render_template, request, abort, Response
from datetime import datetime
from models import db, Provider
from slugify import slugify  

def create_app():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///directory.db"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    with app.app_context():
        db.create_all()

    @app.route("/")
    def home():
        # small “proof it’s real” stats
        total = Provider.query.count()
        remote_count = Provider.query.filter_by(offers_remote=True).count()
        golf_count = Provider.query.filter(Provider.primary_sport.ilike("%golf%")).count()
        return render_template("home.html", total=total, remote_count=remote_count, golf_count=golf_count)

    @app.route("/sitemap.xml")
    def sitemap():
        """
        Dynamic sitemap including:
        - core pages
        - all provider detail pages (/coach/<slug>)
        - all tag pages (/tag/<tag-slug>) derived from Provider.focus_tags
        """
        base_url = request.url_root.rstrip("/")  # e.g., http://127.0.0.1:5000
        today = datetime.utcnow().date().isoformat()

        urls = []

        # Core pages (adjust if your routes differ)
        core_paths = [
            "/",                # homepage
            "/coaches",          # browse list
            "/for-providers",    # get listed page
        ]
        for path in core_paths:
            urls.append({
                "loc": f"{base_url}{path}",
                "lastmod": today,
                "changefreq": "weekly",
                "priority": "0.8" if path == "/" else "0.6"
            })

        # Provider pages
        providers = Provider.query.order_by(Provider.provider_name.asc()).all()
        for p in providers:
            if not p.slug:
                continue
            urls.append({
                "loc": f"{base_url}/coach/{p.slug}",
                "lastmod": today,
                "changefreq": "monthly",
                "priority": "0.7"
            })

        # Tag pages (extract unique tags from focus_tags)
        tag_set = set()
        for p in providers:
            if not p.focus_tags:
                continue
            raw_tags = [t.strip() for t in p.focus_tags.split(",") if t.strip()]
            for t in raw_tags:
                tag_set.add(t.lower())

        # Build tag URLs
        for tag in sorted(tag_set):
            tag_slug = slugify(tag)
            urls.append({
                "loc": f"{base_url}/tag/{tag_slug}",
                "lastmod": today,
                "changefreq": "weekly",
                "priority": "0.6"
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

    @app.route("/coaches")
    def coaches():
        sport = (request.args.get("sport") or "").strip()
        remote = (request.args.get("remote") or "").strip()  # "1" => True filter
        tag = (request.args.get("tag") or "").strip()

        q = Provider.query

        # Always juniors-first for MVP; you can relax later if desired
        q = q.filter_by(works_with_juniors=True)

        if sport:
            q = q.filter(Provider.primary_sport.ilike(f"%{sport}%"))

        if remote == "1":
            q = q.filter_by(offers_remote=True)

        if tag:
            # simple contains match for comma-separated tags
            q = q.filter(Provider.focus_tags.ilike(f"%{tag}%"))

        providers = q.order_by(Provider.provider_name.asc()).all()

        # Build filter options
        sports = [r[0] for r in db.session.query(Provider.primary_sport).distinct().all() if r[0]]
        sports = sorted(set([s.strip() for s in sports if s.strip()]))

        # Tag options (derived)
        all_tags = set()
        for p in Provider.query.all():
            for t in p.tags_list():
                all_tags.add(t)
        tags = sorted(all_tags)

        return render_template(
            "coaches.html",
            providers=providers,
            sports=sports,
            tags=tags,
            selected_sport=sport,
            selected_remote=(remote == "1"),
            selected_tag=tag
        )

    @app.route("/junior-golf-mental-coach")
    def junior_golf_page():
        providers = (
            Provider.query
            .filter(Provider.focus_tags.ilike("%golf%"))
            .filter_by(works_with_juniors=True)
            .order_by(Provider.provider_name.asc())
            .all()
        )

        return render_template(
            "seo_golf.html",
            providers=providers,
            total=len(providers)
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

    @app.route("/tag/<tag_slug>")
    def tag_page(tag_slug):
        # Convert URL slug -> human readable tag
        # e.g., "fear-of-failure" -> "fear of failure"
        tag_text = tag_slug.replace("-", " ").strip()

        # Query providers that contain this tag
        providers = (
            Provider.query
            .filter(Provider.focus_tags.ilike(f"%{tag_text}%"))
            .filter_by(works_with_juniors=True)
            .order_by(Provider.provider_name.asc())
            .all()
        )

        # SEO strings
        tag_title = tag_text.title()
        page_title = f"{tag_title} | Junior Mental Performance Finder"
        h1 = f"{tag_title} Coaches for Junior Athletes"

        # Optional: canonicalize weird inputs by redirecting to a cleaned slug
        # This keeps URLs consistent (good for SEO)
        canonical_slug = slugify(tag_text)
        canonical_url = f"/tag/{canonical_slug}"

        return render_template(
            "seo_tag.html",
            providers=providers,
            total=len(providers),
            tag_title=tag_title,
            tag_text=tag_text,
            tag_slug=canonical_slug,
            page_title=page_title,
            h1=h1,
            canonical_url=canonical_url
        )

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
