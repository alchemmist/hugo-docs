import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description="Create a documentation site using Alchemmist Docs.")
parser.add_argument("destination", type=Path)
parser.add_argument("--title", default="My documentation")
parser.add_argument("--language", choices=["en", "ru"], default="en")
args = parser.parse_args()
destination = args.destination.resolve()
if destination.exists():
    parser.error(f"Destination already exists: {destination}")
shutil.copytree(ROOT / "starter", destination)
config = destination / "hugo.toml"
text = config.read_text().replace("'My documentation'", json.dumps(args.title, ensure_ascii=False))
text = text.replace("defaultContentLanguage = 'en'", f"defaultContentLanguage = '{args.language}'")
config.write_text(text)
print(f"Created {destination}")
print(f"Run make up in {destination}, then open http://localhost:1320/")
