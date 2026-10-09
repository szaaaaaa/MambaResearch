"""Build the standalone Windows-x64 plugin; never include user files or secrets."""

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.request import urlopen
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins/mambaresearch"
PYTHON_VERSION = "3.13.16"
PYTHON_URL = f"https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip"


def build(output: Path) -> Path:
    manifest = json.loads((PLUGIN / ".codex-plugin/plugin.json").read_text(encoding="utf-8"))
    subprocess.run(["cmd.exe", "/d", "/c", "npm", "run", "build", "--prefix", "frontend"], cwd=ROOT, check=True)
    cache = (ROOT / ".tmp/plugin-build").resolve()
    if not cache.is_relative_to(ROOT.resolve()):
        raise ValueError("Build cache escapes workspace")
    cache.mkdir(parents=True, exist_ok=True)
    python_zip = cache / f"python-{PYTHON_VERSION}.zip"
    if not python_zip.exists():
        with urlopen(PYTHON_URL, timeout=60) as response:
            content = response.read()
        with ZipFile(BytesIO(content)) as archive:
            if archive.testzip() is not None:
                raise ValueError("Corrupt Python runtime archive")
        python_zip.write_bytes(content)
    with TemporaryDirectory(dir=cache) as temporary:
        stage = Path(temporary)
        runtime = stage / "runtime"
        with ZipFile(python_zip) as archive:
            archive.extractall(runtime)
        (runtime / "python313._pth").write_text("python313.zip\n.\nsite-packages\n../app\nimport site\n", encoding="utf-8")
        # Embedded Python does not process a pip --target directory's .pth files.
        (runtime / "sitecustomize.py").write_text("import site\nfrom pathlib import Path\nsite.addsitedir(str(Path(__file__).parent / 'site-packages'))\n", encoding="utf-8")
        subprocess.run([
            sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-compile", "--ignore-installed",
            "--target", str(runtime / "site-packages"), "--platform", "win_amd64",
            "--python-version", "313", "--implementation", "cp", "--abi", "cp313",
            "--only-binary=:all:", "-r", str(PLUGIN / "requirements.txt"),
        ], check=True)
        application = stage / "app"
        application.mkdir()
        shutil.copy2(ROOT / "app.py", application / "app.py")
        for path in (ROOT / "src").rglob("*.py"):
            if "__pycache__" not in path.parts:
                target = application / "src" / path.relative_to(ROOT / "src")
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
        (application / "configs").mkdir()
        shutil.copy2(ROOT / "configs/plugins.json", application / "configs/plugins.json")
        shutil.copytree(ROOT / "frontend/dist", application / "frontend/dist")
        references = stage / "references"
        for directory, source, glob in (
            ("workflows", ROOT / ".skills-shared", "*/SKILL.md"),
            ("roles", ROOT / ".claude/agents", "*.md"),
        ):
            target = references / directory
            target.mkdir(parents=True)
            for path in sorted(source.glob(glob)):
                name = path.parent.name if directory == "workflows" else path.stem
                text = path.read_text(encoding="utf-8").replace("../../plugins/mambaresearch/skills/mambaresearch/", "../../")
                (target / f"{name}.md").write_text(text, encoding="utf-8")
        for source, target in (
            (application, PLUGIN / "app"), (runtime, PLUGIN / "runtime"),
            (references, PLUGIN / "skills/mambaresearch/references"),
        ):
            if target.is_symlink() or not target.resolve().is_relative_to(PLUGIN.resolve()):
                raise ValueError(f"Generated target escapes plugin: {target}")
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
    subprocess.run([str(PLUGIN / "runtime/python.exe"), "-c", "import mcp,fastapi,pypdfium2,PIL,requests,httpx,pypdf; from app import create_app; create_app(); print('Standalone runtime imports OK')"], cwd=PLUGIN, check=True)
    output.mkdir(parents=True, exist_ok=True)
    result = output / f"mambaresearch-{manifest['version']}-windows-x64.zip"
    marketplace = {
        "name": "mambaresearch-local",
        "plugins": [{"name": "mambaresearch", "source": {"source": "local", "path": "./mambaresearch"}, "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Research"}],
    }
    with ZipFile(result, "w", ZIP_DEFLATED) as archive:
        included = [PLUGIN / path for path in (
            ".codex-plugin/plugin.json", ".mcp.json", "requirements.txt",
            "skills/mambaresearch/SKILL.md", "skills/mambaresearch/scripts/check_pdf_text.py",
        )]
        for directory in ("app", "runtime", "skills/mambaresearch/references"):
            included.extend(path for path in (PLUGIN / directory).rglob("*") if path.is_file())
        for path in sorted(included):
            if "__pycache__" not in path.parts and path.suffix != ".pyc":
                archive.write(path, Path("mambaresearch") / path.relative_to(PLUGIN))
        archive.writestr(".agents/plugins/marketplace.json", json.dumps(marketplace, ensure_ascii=False, indent=2))
    digest = hashlib.sha256(result.read_bytes()).hexdigest()
    result.with_suffix(".zip.sha256").write_text(f"{digest}  {result.name}\n", encoding="utf-8")
    print(f"Built {result} ({result.stat().st_size} bytes, SHA256 {digest})")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    build(parser.parse_args().output)
