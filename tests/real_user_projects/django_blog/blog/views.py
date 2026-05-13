from pathlib import Path


def post_detail(slug: str) -> str:
    template = Path("templates/blog/post_detail.html")
    if not template.exists():
        raise FileNotFoundError("Template does not exist: templates/blog/post_detail.html")
    return template.read_text(encoding="utf-8").format(slug=slug)
