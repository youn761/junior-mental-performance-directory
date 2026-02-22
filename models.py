from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Index

db = SQLAlchemy()

class Provider(db.Model):
    __tablename__ = "providers"

    id = db.Column(db.Integer, primary_key=True)

    provider_name = db.Column(db.String(255), nullable=False)
    slug = db.Column(db.String(255), nullable=False, unique=True, index=True)

    website_url = db.Column(db.String(1024), nullable=True)

    primary_sport = db.Column(db.String(80), nullable=True)  # Golf, Multi-sport, etc.
    works_with_juniors = db.Column(db.Boolean, nullable=False, default=True)
    offers_remote = db.Column(db.Boolean, nullable=False, default=False)

    city = db.Column(db.String(120), nullable=True)
    state = db.Column(db.String(40), nullable=True)

    short_description = db.Column(db.Text, nullable=True)
    focus_tags = db.Column(db.String(512), nullable=True)  # comma-separated tags

    created_at = db.Column(db.DateTime, server_default=db.func.now())

    __table_args__ = (
        Index("ix_providers_sport_remote", "primary_sport", "offers_remote"),
    )

    def tags_list(self):
        if not self.focus_tags:
            return []
        return [t.strip() for t in self.focus_tags.split(",") if t.strip()]
