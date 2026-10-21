"""Export an allowlisted source snapshot without Git history or research data."""
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "scripts/create_demo_db.py", "docs/getting-started.md", "docs/system-guide.md",
    "examples/demo/.env.example", "examples/demo/schema_summary.md",
    "examples/demo/value_aliases.json", "examples/demo/analysis_semantics.json",
    "README.md", ".gitignore", ".env.example", ".python-version",
    "pyproject.toml", "uv.lock", "package.json", "main.py",
    ".github/workflows/ci.yml", "scripts/export_public.py",
    "docs/images/prompt-result.png", "docs/images/follow-up-result.png",
    "docs/images/agent2ui-plan.png", "docs/images/interaction-flow.png",
    "docs/images/evaluation-process.png",
    "docs/images/system-architecture.png", "docs/images/plan-to-ui-example.png",
    "Data/docs/schema_summary.md", "Data/docs/analysis_semantics.json",
    "Data/docs/value_aliases.json", "Data/migrations/001_analysis_views.sql",
)
EXTENSIONS = {".py", ".md", ".json", ".html", ".css", ".js"}


def main():
    paths = {ROOT / name for name in FILES}
    for directory in ("app", "tests"):
        paths.update(
            path for path in (ROOT / directory).rglob("*")
            if path.is_file() and path.suffix in EXTENSIONS
            and "__pycache__" not in path.parts
            and not any(part.startswith(".") for part in path.relative_to(ROOT).parts)
        )
    missing = [str(path.relative_to(ROOT)) for path in paths if not path.is_file()]
    if missing:
        raise SystemExit(f"Missing public source files: {missing}")
    target = ROOT / "dist" / "order-ui-agent-public.zip"
    target.parent.mkdir(exist_ok=True)
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        for path in sorted(paths):
            archive.write(path, Path("order-ui-agent") / path.relative_to(ROOT))
    print(f"Created {target} ({len(paths)} files)")


if __name__ == "__main__":
    main()
