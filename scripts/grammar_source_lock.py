#!/usr/bin/env python3
"""Maintain grammar_sources.lock.json for fixed-output Helix grammar fetchers."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
LANGUAGES_TOML = ROOT / "languages.toml"
LOCK_PATH = ROOT / "grammar_sources.lock.json"
LOCK_VERSION = 1
GITHUB_PREFIX = "https://github.com/"
GITHUB_RE = re.compile(r"https://github\.com/([^/]+)/([^/]+)/?")


@dataclass(frozen=True)
class GrammarSource:
    name: str
    git: str
    rev: str

    @property
    def cache_key(self) -> tuple[str, str, str]:
        if self.git.startswith(GITHUB_PREFIX):
            owner, repo = parse_github(self.git)
            return ("github", owner, f"{repo}:{self.rev}")
        return ("git", self.git, self.rev)

    def lock_entry(self, sha256: str) -> dict[str, Any]:
        if self.git.startswith(GITHUB_PREFIX):
            owner, repo = parse_github(self.git)
            return {
                "fetcher": "github",
                "owner": owner,
                "repo": repo,
                "rev": self.rev,
                "hash": sha256,
            }
        return {
            "fetcher": "git",
            "url": self.git,
            "rev": self.rev,
            "hash": sha256,
        }


def parse_github(url: str) -> tuple[str, str]:
    match = GITHUB_RE.match(url)
    if match is None:
        raise ValueError(f"invalid GitHub grammar URL: {url}")
    return match.group(1), match.group(2)


def load_languages_config() -> dict[str, Any]:
    with LANGUAGES_TOML.open("rb") as handle:
        return tomllib.load(handle)


def active_grammar_sources(config: dict[str, Any]) -> list[GrammarSource]:
    use_grammars = config.get("use-grammars", {})
    only = set(use_grammars.get("only", []))
    except_ = set(use_grammars.get("except", []))

    sources: list[GrammarSource] = []
    for grammar in config.get("grammar", []):
        name = grammar["name"]
        if only and name not in only:
            continue
        if except_ and name in except_:
            continue
        source = grammar.get("source", {})
        git = source.get("git")
        rev = source.get("rev")
        if not git or not rev:
            continue
        sources.append(GrammarSource(name=name, git=git, rev=rev))
    return sorted(sources, key=lambda item: item.name)


def run_json_command(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def prefetch_github(owner: str, repo: str, rev: str) -> str:
    payload = run_json_command(
        [
            "nix",
            "run",
            "nixpkgs#nix-prefetch-github",
            "--",
            "--json",
            "--rev",
            rev,
            owner,
            repo,
        ]
    )
    return payload["hash"]


def prefetch_git(url: str, rev: str) -> str:
    payload = run_json_command(
        [
            "nix",
            "run",
            "nixpkgs#nix-prefetch-git",
            "--",
            "--json",
            "--url",
            url,
            "--rev",
            rev,
        ]
    )
    return payload["hash"]


def prefetch_source(source: GrammarSource) -> str:
    if source.git.startswith(GITHUB_PREFIX):
        owner, repo = parse_github(source.git)
        return prefetch_github(owner, repo, source.rev)
    return prefetch_git(source.git, source.rev)


def build_lock(sources: list[GrammarSource], jobs: int) -> dict[str, Any]:
    unique_sources: dict[tuple[str, str, str], GrammarSource] = {}
    for source in sources:
        unique_sources[source.cache_key] = source

    hashes: dict[tuple[str, str, str], str] = {}
    failures: list[str] = []

    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {
            pool.submit(prefetch_source, source): key
            for key, source in unique_sources.items()
        }
        for future in as_completed(futures):
            key = futures[future]
            source = unique_sources[key]
            try:
                hashes[key] = future.result()
            except subprocess.CalledProcessError as err:
                failures.append(
                    f"{source.name}: prefetch failed ({err.stderr.strip() or err})"
                )

    if failures:
        raise SystemExit("grammar source prefetch failed:\n" + "\n".join(failures))

    grammars = {
        source.name: source.lock_entry(hashes[source.cache_key]) for source in sources
    }
    return {"version": LOCK_VERSION, "grammars": grammars}


def load_lock() -> dict[str, Any]:
    with LOCK_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_lock(lock: dict[str, Any]) -> None:
    LOCK_PATH.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def validate_lock() -> list[str]:
    config = load_languages_config()
    sources = active_grammar_sources(config)
    if not LOCK_PATH.exists():
        return [f"missing lock file: {LOCK_PATH}"]

    lock = load_lock()
    errors: list[str] = []

    if lock.get("version") != LOCK_VERSION:
        errors.append(
            f"unsupported lock version {lock.get('version')}; expected {LOCK_VERSION}"
        )

    lock_grammars = lock.get("grammars", {})
    expected_names = {source.name for source in sources}
    actual_names = set(lock_grammars)
    missing = sorted(expected_names - actual_names)
    extra = sorted(actual_names - expected_names)
    if missing:
        errors.append(f"missing lock entries: {', '.join(missing)}")
    if extra:
        errors.append(f"stale lock entries: {', '.join(extra)}")

    for source in sources:
        entry = lock_grammars.get(source.name)
        if entry is None:
            continue
        if entry.get("rev") != source.rev:
            errors.append(
                f"{source.name}: lock rev {entry.get('rev')} != languages.toml rev {source.rev}"
            )
        if source.git.startswith(GITHUB_PREFIX):
            owner, repo = parse_github(source.git)
            if entry.get("fetcher") != "github":
                errors.append(f"{source.name}: expected github fetcher")
            if entry.get("owner") != owner or entry.get("repo") != repo:
                errors.append(f"{source.name}: github owner/repo drift")
        else:
            if entry.get("fetcher") != "git":
                errors.append(f"{source.name}: expected git fetcher")
            if entry.get("url") != source.git:
                errors.append(f"{source.name}: git url drift")

    return errors


def cmd_update(args: argparse.Namespace) -> int:
    config = load_languages_config()
    sources = active_grammar_sources(config)
    if args.grammar:
        selected = {name for name in args.grammar}
        sources = [source for source in sources if source.name in selected]
        if not sources:
            raise SystemExit("no matching grammars selected")

    print(f"prefetching {len(sources)} grammar sources with {args.jobs} workers")
    lock = build_lock(sources, jobs=args.jobs)

    if args.grammar and LOCK_PATH.exists():
        existing = load_lock()
        existing.setdefault("grammars", {}).update(lock["grammars"])
        lock = {"version": LOCK_VERSION, "grammars": existing["grammars"]}

    write_lock(lock)
    print(f"wrote {LOCK_PATH} ({len(lock['grammars'])} entries)")
    return 0


def cmd_validate(_: argparse.Namespace) -> int:
    errors = validate_lock()
    if errors:
        print("grammar source lock validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"grammar source lock is valid ({LOCK_PATH})")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    update = subparsers.add_parser("update", help="regenerate grammar_sources.lock.json")
    update.add_argument(
        "--jobs",
        type=int,
        default=8,
        help="parallel prefetch workers (default: 8)",
    )
    update.add_argument(
        "--grammar",
        action="append",
        default=[],
        help="update only the named grammar(s); can be repeated",
    )
    update.set_defaults(func=cmd_update)

    validate = subparsers.add_parser("validate", help="check lock against languages.toml")
    validate.set_defaults(func=cmd_validate)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())