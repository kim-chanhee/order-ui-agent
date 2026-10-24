"""Export an allowlisted source snapshot without Git history or research data."""
import json
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "docs/experiments/README.md", "docs/experiments/participant-guide-v2.md",
    "docs/experiments/study-results.md", "docs/experiments/sources.json",
    "docs/experiments/originals/participant-guide-v2.docx",
    "docs/experiments/originals/study-results.docx",
    "docs/experiments/images/study-results-1.png",
    "docs/experiments/images/study-results-2.png",
    "scripts/create_demo_db.py", "docs/getting-started.md", "docs/system-guide.md",
    "examples/demo/.env.example", "examples/demo/schema_summary.md",
    "examples/demo/value_aliases.json", "examples/demo/analysis_semantics.json",
    "Data/README.md", "Data/A2UI/README.md", "Data/A2UI/analysis_common.py",
    'Data/A2UI/01_측정도구신뢰도_Cronbach_alpha.ipynb',
    'Data/A2UI/02_기술통계.ipynb',
    'Data/A2UI/03_상관분석_Pearson.ipynb',
    'Data/A2UI/04-1_사후설문_ANOVA_가정검정.ipynb',
    'Data/A2UI/04-2_사후설문_ANOVA_가정검정과_BoxCox_재분석.ipynb',
    'Data/A2UI/04_이원분산분석_UI유형x숙련도.ipynb',
    'Data/A2UI/05_Log분석.ipynb',
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



def public_content(path: Path) -> bytes:
    """Remove notebook outputs and private study references on every export."""
    if path.suffix == ".ipynb":
        notebook = json.loads(path.read_text(encoding="utf-8"))
        for cell in notebook["cells"]:
            source = "".join(cell.get("source", []))
            source = re.sub(r"https://docs\.google\.com/spreadsheets/[^\s\"']+", "private-survey-source", source)
            source = re.sub(r"REANALYSIS_THREADS = \{[^}]*\}", "REANALYSIS_THREADS = set(common.REANALYSIS_THREADS)", source)
            cell["source"] = source.splitlines(keepends=True)
            cell["metadata"] = {}
            cell.pop("attachments", None)
            if cell["cell_type"] == "code":
                cell["outputs"] = []
                cell["execution_count"] = None
        notebook["metadata"] = {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python"},
        }
        return (json.dumps(notebook, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    if path.name == "analysis_common.py":
        source = path.read_text(encoding="utf-8")
        if "EXCLUSIONS_FILE =" not in source:
            source = source.replace("import hashlib", "import hashlib\nimport json", 1)
            source = source.replace(
                "RESULT_DIR = A2UI_DIR / 'results'",
                "RESULT_DIR = A2UI_DIR / 'results'\n"
                "EXCLUSIONS_FILE = A2UI_DIR / 'analysis_exclusions.json'\n"
                "REANALYSIS_THREADS = (\n"
                "    json.loads(EXCLUSIONS_FILE.read_text(encoding='utf-8')).get('reanalysis_threads', [])\n"
                "    if EXCLUSIONS_FILE.exists() else []\n)"
            )
        return source.encode("utf-8")
    return path.read_bytes()


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
            archive.writestr(str(Path("order-ui-agent") / path.relative_to(ROOT)), public_content(path))
    print(f"Created {target} ({len(paths)} files)")


if __name__ == "__main__":
    main()
