from pathlib import Path


EXPORT_PATH = Path("var/exports/latest/customers.csv")

with EXPORT_PATH.open(encoding="utf-8") as handle:
    print(handle.readline())
