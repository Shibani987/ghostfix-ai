import os
from pathlib import Path


report_target = Path(__file__).parent / "readonly_file.txt"
report_target.write_text("existing content")
os.chmod(report_target, 0o444)  # read-only for all users
with report_target.open("w", encoding="utf-8") as handle:
    handle.write("daily revenue report")
