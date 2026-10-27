#!/usr/bin/env python3
"""Report outdated Homebrew packages with upgrade-decision context."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GITHUB_TIMEOUT_SECONDS = 10
GITHUB_WORKERS = 8


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "List outdated Homebrew formulae and casks (including auto-updating casks) "
            "with dependents, coupled upgrades, version-bump size, and recipe age."
        )
    )
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="skip GitHub lookups; recipe ages come only from local taps and the cache",
    )
    return parser.parse_args()


def status(message: str) -> None:
    if sys.stderr.isatty():
        print(message, file=sys.stderr)


def run(argv: list[str], timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def brew_json(args: list[str], warnings: list[str]) -> Any:
    result = run(["brew", *args])
    if result.returncode != 0:
        sys.exit(f"brew {' '.join(args)} failed:\n{result.stderr.strip()}")
    stderr = result.stderr.strip()
    if stderr and stderr not in warnings:
        warnings.append(stderr)
    return json.loads(result.stdout)


def iso(timestamp: float | None) -> str | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def age_days(timestamp: float | None, now: float) -> float | None:
    if timestamp is None:
        return None
    return round(max(0.0, now - timestamp) / 86400, 1)


# --- Version comparison ----------------------------------------------------


def split_revision(version: str) -> tuple[str, str]:
    match = re.fullmatch(r"(.+?)_(\d+)", version)
    return (match.group(1), match.group(2)) if match else (version, "0")


def bump_kind(installed: str, current: str) -> str:
    """Classify a version change as major, minor, patch, revision, or other."""
    if installed == current:
        return "none"
    old_base, old_rev = split_revision(installed.split(",")[0])
    new_base, new_rev = split_revision(current.split(",")[0])
    if old_base == new_base:
        return "revision" if old_rev != new_rev else "other"
    old_parts = re.split(r"[.\-+]", old_base)
    new_parts = re.split(r"[.\-+]", new_base)
    if not (old_parts[0].isdigit() and new_parts[0].isdigit()):
        return "other"
    for index, (old, new) in enumerate(zip(old_parts, new_parts)):
        if old != new:
            return ("major", "minor")[index] if index < 2 else "patch"
    return "patch"


# --- Package indexes -------------------------------------------------------


def index_formulae(formulae: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for formula in formulae:
        for key in [formula["name"], formula["full_name"], *formula.get("aliases", []), *formula.get("oldnames", [])]:
            index.setdefault(key, formula)
    return index


def index_casks(casks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for cask in casks:
        for key in [cask["full_token"], cask["token"], *cask.get("old_tokens", [])]:
            index.setdefault(key, cask)
    return index


def canonical(name: str, formula_index: dict[str, dict[str, Any]]) -> str:
    formula = formula_index.get(name) or formula_index.get(name.rsplit("/", 1)[-1])
    return formula["full_name"] if formula else name


def direct_dependents(
    formulae: list[dict[str, Any]],
    casks: list[dict[str, Any]],
    formula_index: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    """Map each formula to installed packages that declare it directly, like `brew uses --installed`."""
    dependents: dict[str, set[str]] = {}
    for formula in formulae:
        declared = formula.get("dependencies", []) + formula.get("recommended_dependencies", [])
        for dep in declared:
            dependents.setdefault(canonical(dep, formula_index), set()).add(formula["full_name"])
    for cask in casks:
        for dep in cask.get("depends_on", {}).get("formula", []):
            dependents.setdefault(canonical(dep, formula_index), set()).add(cask["full_token"])
    return {name: sorted(names) for name, names in dependents.items()}


def new_cask_dependencies(
    names: list[str],
    formula_index: dict[str, dict[str, Any]],
    cask_index: dict[str, dict[str, Any]],
    warnings: list[str],
) -> dict[str, list[str]]:
    """Map each cask to packages it would pull in that are not installed; cask dry runs omit these."""

    def is_installed(dep: str) -> bool:
        # Deps can be formulae or casks, printed short or tap-qualified.
        return any(key in index for key in (dep, dep.rsplit("/", 1)[-1]) for index in (formula_index, cask_index))

    if not names:
        return {}
    result = run(["brew", "deps", "--cask", "--for-each", *names])
    if result.returncode != 0:
        warnings.append(f"Could not list cask dependencies:\n{result.stderr.strip()}")
        return {}
    missing: dict[str, list[str]] = {}
    for line in result.stdout.splitlines():
        cask, _, deps = line.partition(":")
        missing[cask.strip().rsplit("/", 1)[-1]] = sorted(dep for dep in deps.split() if not is_installed(dep))
    return missing


def runtime_dependencies(formula: dict[str, Any], formula_index: dict[str, dict[str, Any]]) -> set[str]:
    installed = formula.get("installed") or [{}]
    return {canonical(dep["full_name"], formula_index) for dep in installed[-1].get("runtime_dependencies") or []}


# --- Recipe ages -----------------------------------------------------------


def cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "brew-upgrade" / "recipe-dates.json"


def load_cache() -> dict[str, float]:
    try:
        data = json.loads(cache_path().read_text())
    except (OSError, ValueError):
        return {}
    return {key: value for key, value in data.items() if isinstance(value, (int, float))}


def save_cache(cache: dict[str, float]) -> None:
    path = cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as handle:
            json.dump(cache, handle, indent=1, sort_keys=True)
        os.replace(handle.name, path)
    except OSError:
        pass


def tap_dir(brew_repository: Path, tap: str) -> Path | None:
    owner, _, repo = tap.partition("/")
    if not owner or not repo:
        return None
    return brew_repository / "Library" / "Taps" / owner / f"homebrew-{repo}"


def github_repo(tap: str) -> str | None:
    owner, _, repo = tap.partition("/")
    if not owner or not repo:
        return None
    return f"Homebrew/homebrew-{repo}" if owner == "homebrew" else f"{owner}/homebrew-{repo}"


def local_commit_time(directory: Path, source_path: str) -> float | None:
    if not (directory / ".git").exists():
        return None
    result = run(["git", "-C", str(directory), "log", "-1", "--format=%ct", "--", source_path])
    output = result.stdout.strip()
    return float(output) if result.returncode == 0 and output else None


def parse_github_date(value: str) -> float | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def github_commit_time(repo: str, source_path: str, use_gh: bool) -> float | None:
    endpoint = f"repos/{repo}/commits?path={urllib.parse.quote(source_path)}&per_page=1"
    try:
        if use_gh:
            result = run(["gh", "api", endpoint, "--jq", ".[0].commit.committer.date"], timeout=GITHUB_TIMEOUT_SECONDS)
            return parse_github_date(result.stdout.strip()) if result.returncode == 0 else None
        request = urllib.request.Request(
            f"https://api.github.com/{endpoint}", headers={"Accept": "application/vnd.github+json"}
        )
        with urllib.request.urlopen(request, timeout=GITHUB_TIMEOUT_SECONDS) as response:
            commits = json.load(response)
        return parse_github_date(commits[0]["commit"]["committer"]["date"]) if commits else None
    except (OSError, ValueError, KeyError, IndexError, subprocess.TimeoutExpired):
        return None


def gh_authenticated() -> bool:
    if not shutil.which("gh"):
        return False
    try:
        return run(["gh", "auth", "status"], timeout=GITHUB_TIMEOUT_SECONDS).returncode == 0
    except subprocess.TimeoutExpired:
        return False


def fill_recipe_ages(items: list[dict[str, Any]], brew_repository: Path, offline: bool, warnings: list[str]) -> None:
    """Set recipe_updated_at: the last commit touching each package's formula or cask file."""
    cache = load_cache()
    remote: list[tuple[dict[str, Any], str, str, str]] = []

    for item in items:
        tap, source_path = item.pop("_tap_source")
        item["recipe_updated_at"] = None
        item["recipe_age_source"] = None
        if not tap or not source_path:
            continue
        directory = tap_dir(brew_repository, tap)
        timestamp = local_commit_time(directory, source_path) if directory else None
        if timestamp is not None:
            item["_recipe_time"], item["recipe_age_source"] = timestamp, "local-tap"
            continue
        key = f"{tap}:{source_path}@{item['current_version']}"
        if key in cache:
            item["_recipe_time"], item["recipe_age_source"] = cache[key], "cache"
            continue
        repo = github_repo(tap)
        if repo and not offline:
            remote.append((item, repo, source_path, key))

    if remote:
        use_gh = gh_authenticated()
        if not use_gh:
            warnings.append("gh is not authenticated; using unauthenticated GitHub API (60 requests/hour).")
        status(f"Looking up {len(remote)} recipe dates on GitHub...")
        with ThreadPoolExecutor(max_workers=GITHUB_WORKERS) as pool:
            times = list(pool.map(lambda job: github_commit_time(job[1], job[2], use_gh), remote))
        for (item, _repo, _path, key), timestamp in zip(remote, times):
            if timestamp is None:
                continue
            item["_recipe_time"], item["recipe_age_source"] = timestamp, "github"
            cache[key] = timestamp
        save_cache(cache)

    missing = [item["name"] for item in items if item.get("_recipe_time") is None]
    if missing:
        warnings.append(f"Recipe age unknown for: {', '.join(missing)}")


# --- Collection ------------------------------------------------------------


def app_versions(cask: dict[str, Any]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for artifact in cask.get("artifacts", []):
        target = artifact.get("target") if isinstance(artifact, dict) and "app" in artifact else None
        if not target:
            continue
        try:
            with open(Path(target) / "Contents" / "Info.plist", "rb") as handle:
                info = plistlib.load(handle)
        except (OSError, plistlib.InvalidFileException, ValueError):
            continue
        version = info.get("CFBundleShortVersionString") or info.get("CFBundleVersion")
        if version:
            versions[target] = str(version)
    return versions


def tap_fetch_times(brew_repository: Path) -> dict[str, str | None]:
    """Last `git fetch` of each locally cloned tap; only `brew update` refreshes these."""
    fetched: dict[str, str | None] = {}
    for git_dir in sorted((brew_repository / "Library" / "Taps").glob("*/homebrew-*/.git")):
        owner, repo = git_dir.parent.parent.name, git_dir.parent.name[len("homebrew-") :]
        fetch_head = git_dir / "FETCH_HEAD"
        fetched[f"{owner}/{repo}"] = iso(fetch_head.stat().st_mtime) if fetch_head.exists() else None
    return fetched


def collect(offline: bool) -> dict[str, Any]:
    warnings: list[str] = []
    now = time.time()

    status("Checking outdated packages...")
    outdated = brew_json(["outdated", "--json=v2", "--greedy"], warnings)
    status("Loading installed package metadata...")
    installed = brew_json(["info", "--json=v2", "--installed"], warnings)
    brew_repository = Path(run(["brew", "--repository"]).stdout.strip())

    formulae = installed.get("formulae", [])
    casks = installed.get("casks", [])
    formula_index = index_formulae(formulae)
    cask_index = index_casks(casks)
    dependents = direct_dependents(formulae, casks, formula_index)

    outdated_formula_names = {canonical(entry["name"], formula_index) for entry in outdated.get("formulae", [])}
    runtime = {formula["full_name"]: runtime_dependencies(formula, formula_index) for formula in formulae}

    items: list[dict[str, Any]] = []
    for entry in outdated.get("formulae", []):
        formula = formula_index.get(entry["name"], {})
        name = formula.get("full_name", entry["name"])
        installed_version = (entry["installed_versions"] or [""])[-1]
        records = formula.get("installed") or [{}]
        items.append(
            {
                "kind": "formula",
                "name": name,
                "installed_versions": entry["installed_versions"],
                "current_version": entry["current_version"],
                "bump": bump_kind(installed_version, entry["current_version"]),
                "pinned": entry.get("pinned", False),
                "deprecated": formula.get("deprecated", False),
                "disabled": formula.get("disabled", False),
                "tap": formula.get("tap"),
                "installed_on_request": records[-1].get("installed_on_request"),
                "dependents": dependents.get(name, []),
                "outdated_dependencies": sorted(runtime.get(name, set()) & outdated_formula_names),
                "outdated_dependents": sorted(
                    other for other in outdated_formula_names if name in runtime.get(other, set())
                ),
                "_tap_source": (formula.get("tap"), formula.get("ruby_source_path")),
            }
        )

    cask_entries = outdated.get("casks", [])
    cask_new_deps = new_cask_dependencies(
        [entry["name"] for entry in cask_entries], formula_index, cask_index, warnings
    )
    for entry in cask_entries:
        cask = cask_index.get(entry["name"], {})
        installed_version = (entry["installed_versions"] or [""])[-1]
        items.append(
            {
                "kind": "cask",
                "name": cask.get("full_token", entry["name"]),
                "installed_versions": entry["installed_versions"],
                "current_version": entry["current_version"],
                "bump": bump_kind(installed_version, entry["current_version"]),
                "pinned": entry.get("pinned", False),
                "deprecated": cask.get("deprecated", False),
                "disabled": cask.get("disabled", False),
                "tap": cask.get("tap"),
                "auto_updates": bool(cask.get("auto_updates")),
                "version_latest": cask.get("version") == "latest",
                "app_versions": app_versions(cask),
                "new_dependencies": cask_new_deps.get(entry["name"].rsplit("/", 1)[-1], []),
                "_tap_source": (cask.get("tap"), cask.get("ruby_source_path")),
            }
        )

    fill_recipe_ages(items, brew_repository, offline, warnings)
    for item in items:
        timestamp = item.pop("_recipe_time", None)
        item["recipe_updated_at"] = iso(timestamp)
        item["recipe_age_days"] = age_days(timestamp, now)

    return {
        "generated_at": iso(now),
        "taps_fetched_at": tap_fetch_times(brew_repository),
        "packages": items,
        "warnings": warnings,
    }


# --- Table output ----------------------------------------------------------


def format_age(days: float | None) -> str:
    if days is None:
        return "?"
    if days < 1:
        return f"{round(days * 24)}h"
    if days < 60:
        return f"{days:.0f}d"
    return f"{days / 30:.0f}mo"


def notes_for(item: dict[str, Any]) -> str:
    notes: list[str] = []
    if item["kind"] == "cask":
        notes.append("cask")
        if item["auto_updates"] or item["version_latest"]:
            notes.append("self-updating")
        for version in item["app_versions"].values():
            notes.append(f"app {version}")
        if item["new_dependencies"]:
            notes.append("installs " + " ".join(item["new_dependencies"]))
    elif item["dependents"]:
        notes.append("← " + " ".join(item["dependents"]))
    else:
        notes.append("top level")
    if item.get("outdated_dependencies") or item.get("outdated_dependents"):
        coupled = sorted(set(item["outdated_dependencies"]) | set(item["outdated_dependents"]))
        notes.append("with " + " ".join(coupled))
    for flag in ("pinned", "deprecated", "disabled"):
        if item[flag]:
            notes.append(flag)
    return "; ".join(notes)


def print_table(report: dict[str, Any]) -> None:
    rows = [
        (
            item["name"],
            f"{item['installed_versions'][-1] if item['installed_versions'] else '?'} → {item['current_version']}",
            item["bump"],
            format_age(item["recipe_age_days"]),
            notes_for(item),
        )
        for item in report["packages"]
    ]
    if not rows:
        print("Everything is up to date.")
    widths = [max((len(row[column]) for row in rows), default=0) for column in range(4)]
    color = sys.stdout.isatty()
    for row in rows:
        cells = [cell.ljust(width) for cell, width in zip(row[:4], widths)] + [row[4]]
        if color:
            cells[0] = f"\033[1m{cells[0]}\033[0m"
            cells[3] = f"\033[38;5;179m{cells[3]}\033[0m"
            cells[4] = f"\033[90m{cells[4]}\033[0m"
        print("  ".join(cells))
    for warning in report["warnings"]:
        print(f"\nwarning: {warning}", file=sys.stderr)


def main() -> int:
    args = parse_args()
    report = collect(args.offline)
    if args.json:
        json.dump(report, sys.stdout, indent=2)
        print()
    else:
        print_table(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
