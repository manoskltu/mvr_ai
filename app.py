"""MVR Offer Tool — Flask application module."""

from flask import Flask, render_template


def create_app() -> Flask:
    """Application factory — creates and returns a configured Flask instance."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    # Ensure UTF-8 charset for Swedish character support (å, ä, ö)
    app.config["JSON_AS_ASCII"] = False

    # Secret key for flash messages
    app.config["SECRET_KEY"] = "dev-secret-key"

    # Database configuration
    app.config.setdefault(
        "SQLALCHEMY_DATABASE_URI", "sqlite:///mvr.db"
    )
    app.config.setdefault("SQLALCHEMY_TRACK_MODIFICATIONS", False)

    # Initialize Flask-SQLAlchemy
    from db_models import db

    db.init_app(app)

    with app.app_context():
        db.create_all()

        # Migration: add file_path column if missing (for existing databases)
        from sqlalchemy import text

        with db.engine.connect() as conn:
            result = conn.execute(text("PRAGMA table_info(attachments)"))
            columns = [row[1] for row in result]
            if "file_path" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE attachments ADD COLUMN file_path TEXT NOT NULL DEFAULT ''"
                    )
                )
                conn.commit()

    # Register the Data Tab blueprint
    from routes.data_routes import data_bp

    app.register_blueprint(data_bp)

    @app.after_request
    def set_charset(response):
        if "text/html" in response.content_type:
            response.headers["Content-Type"] = "text/html; charset=utf-8"
        return response

    @app.route("/")
    def index():
        return render_template(
            "index.html",
            project_name="MVR Offer Tool",
        )

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=5000, debug=False)
