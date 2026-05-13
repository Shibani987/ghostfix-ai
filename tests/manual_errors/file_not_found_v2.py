from pathlib import Path


path = Path("missing_config_v2.json")
content = path.read_text()
print(content)
