"""Minimal Flask app that intentionally raises TemplateNotFound at startup."""

from flask import Flask, render_template


app = Flask(__name__)


@app.get("/")
def index():
    return render_template("dashboard.html")


if __name__ == "__main__":
    with app.app_context():
        render_template("dashboard.html")
