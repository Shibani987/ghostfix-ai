from pathlib import Path


report_target = Path(__file__).parent

with report_target.open("w", encoding="utf-8") as handle:
    handle.write("daily revenue report")
