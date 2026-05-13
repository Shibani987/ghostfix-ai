from pathlib import Path


def main() -> None:
    config = Path("config/local_settings.json")
    print(config.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
