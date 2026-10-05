"""Independently audit the packaged numeric index against the pinned source."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_numeric_rules import COMMIT, NUMBER, UPSTREAM, mask_java


def verify(upstream=UPSTREAM):
    git = shutil.which("git") or "C:/Program Files/Git/cmd/git.exe"
    commit = subprocess.check_output([git, "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output([git, "-C", str(upstream), "status", "--porcelain"], text=True).strip()
    if commit != COMMIT or dirty:
        raise ValueError("Reference source is not the clean pinned revision")
    data = json.loads((ROOT / "data/numeric_rules.json").read_text(encoding="utf-8"))
    count = 0
    for record in data["coverage"]["files"]:
        path = upstream / record["path"]
        text = path.read_text(encoding="utf-8")
        if hashlib.sha256(text.encode()).hexdigest() != record["sha256"]:
            raise ValueError("Source content mismatch: " + record["path"])
        occurrences = len(list(NUMBER.finditer(mask_java(text))))
        if occurrences != record["numeric_literals"] or record["uncovered_literals"]:
            raise ValueError("Numeric coverage mismatch: " + record["path"])
        count += occurrences
        spans = []
        for row in data["classes"].values():
            if row["path"] != record["path"]:
                continue
            for rule in row["rules"]:
                start, end = rule["source_start"], rule["source_end"]
                if text[start:end].strip() != rule["code"]:
                    raise ValueError("Enclosing source rule mismatch: " + rule["id"])
                spans.append((start, end))
        if any(not any(start <= m.start() < end for start, end in spans)
               for m in NUMBER.finditer(mask_java(text))):
            raise ValueError("Literal missing from enclosing rules: " + record["path"])
    actual = set()
    for folder in ("core/src/main/java/com/shatteredpixel/shatteredpixeldungeon", "SPD-classes/src/main/java/com/watabou"):
        actual.update(p.relative_to(upstream).as_posix() for p in (upstream / folder).rglob("*.java"))
    if actual != {r["path"] for r in data["coverage"]["files"]}:
        raise ValueError("Source file inventory mismatch")
    if count != data["coverage"]["numeric_literals"]:
        raise ValueError("Numeric total mismatch")
    # A literal must be inside a rule, not merely counted in a file manifest.
    indexed = sum(len(list(NUMBER.finditer(rule["body"]))) for row in data["classes"].values() for rule in row["rules"])
    if indexed < count:
        raise ValueError("Numerical rules have lost literal occurrences")
    return {"commit": commit, "clean_source": True, "files": len(actual), "numeric_literals": count,
            "indexed_occurrences": indexed, "uncovered": 0, "entry_coverage": data["entry_coverage"]}


if __name__ == "__main__":
    result = verify()
    output = ROOT / ".local/numeric-coverage-verification.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
