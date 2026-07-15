#!/usr/bin/env python3
"""
figma_sync.py

Polls the AQ Metro Figma file for sections/frames that have been marked
"Ready for Dev" using Figma's real Dev Mode status control (devStatus.type
== "READY_FOR_DEV") - NOT a hand-drawn banner or colored rectangle. Any
node with that real status is new or has changed content, its Arabic text
is extracted, translated + structured into this repo's key/value schema via
the Anthropic API, and merged into localization_hub.json.

This script deliberately does NOT commit, push, or merge anything by
itself. It only edits two files on disk:
    - localization_hub.json
    - .figma_sync_state.json
The surrounding GitHub Action (.github/workflows/figma-sync.yml) is
responsible for turning any resulting diff into a pull request, so a human
reviews the translation and key names before they reach main - see the
"Automated Figma Sync" section of README.md for why that review step is
kept as the one remaining manual gate.

Required environment variables:
    FIGMA_TOKEN         Figma personal access token, `file_content:read` scope
    FIGMA_FILE_KEY      The Figma file key, e.g. LRmXlW9xeGKFBGZrMzUrRA
    ANTHROPIC_API_KEY   Used to translate + structure extracted Arabic text

Usage:
    python3 scripts/figma_sync.py
"""

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
JSON_FILE = REPO_ROOT / "localization_hub.json"
STATE_FILE = REPO_ROOT / ".figma_sync_state.json"

FIGMA_TOKEN = os.environ.get("FIGMA_TOKEN")
FIGMA_FILE_KEY = os.environ.get("FIGMA_FILE_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

FIGMA_API = "https://api.figma.com/v1"
ANTHROPIC_API = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-sonnet-5"

# Node types Figma allows a devStatus to be set on directly.
STATUS_ELIGIBLE_TYPES = ("SECTION", "FRAME")


def require_env() -> None:
    missing = [
        name
        for name, value in [
            ("FIGMA_TOKEN", FIGMA_TOKEN),
            ("FIGMA_FILE_KEY", FIGMA_FILE_KEY),
            ("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
        ]
        if not value
    ]
    if missing:
        print(f"Missing required environment variables: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)


def figma_get(path: str) -> dict:
    req = urllib.request.Request(f"{FIGMA_API}{path}", headers={"X-Figma-Token": FIGMA_TOKEN})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"Figma API error {e.code}: {e.read().decode('utf-8', 'ignore')}", file=sys.stderr)
        raise


def find_ready_for_dev_nodes(node: dict, out: list) -> None:
    """Recursively collect nodes whose devStatus.type == READY_FOR_DEV.
    Does not descend further into a node once it's been collected, since its
    whole subtree is what gets extracted and translated as one unit."""
    dev_status = node.get("devStatus")
    if (
        dev_status
        and dev_status.get("type") == "READY_FOR_DEV"
        and node.get("type") in STATUS_ELIGIBLE_TYPES
    ):
        out.append(node)
        return

    for child in node.get("children", []):
        find_ready_for_dev_nodes(child, out)


def collect_text(node: dict, texts: list) -> None:
    if node.get("type") == "TEXT" and node.get("characters"):
        texts.append(node["characters"])
    for child in node.get("children", []):
        collect_text(child, texts)


def content_hash(texts: list) -> str:
    return hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()


def to_screen_key(figma_node_name: str) -> str:
    """Turn a Figma frame/section name like 'Home Page' or 'purchase-ticket'
    into a PascalCase screen key like 'HomePageScreen'."""
    words = [w for w in figma_node_name.replace("-", " ").replace("_", " ").split(" ") if w]
    base = "".join(w.capitalize() for w in words)
    return base if base.endswith("Screen") else f"{base}Screen"


def call_claude_for_translation(screen_name: str, arabic_lines: list) -> dict:
    """Ask Claude to translate + structure the extracted Arabic lines into
    this repo's {key: {ar, en}} schema for a single screen. Returns a dict
    of {key: {"ar": ..., "en": ...}}."""
    prompt = f"""You are localizing UI text for the AQ Metro mobile app (Alexandria Metro).

Below is the raw Arabic text extracted from a Figma frame/section named
"{screen_name}" that has just been marked Ready for Dev. Translate each
distinct piece of text into natural, professional English suitable for a
modern transit app, and return a JSON object mapping a clean snake_case key
to {{"ar": ..., "en": ...}} for each one.

Conventions to follow (matching this repo's existing localization_hub.json):
- Prefix buttons with btn_, field labels with label_, and use _title /
  _description suffixes for headings and body copy.
- Prefer reusing an existing key name and phrasing style if the text is
  clearly the same UI concept as something already common across screens
  (e.g. a login button should be keyed btn_login, a continue button
  btn_continue, a settings nav item nav_settings).
- Skip obvious placeholder/example data such as sample names, emails, phone
  numbers, or dates that are just Figma mock content, not real UI copy.
- Return ONLY valid JSON - no markdown code fences, no commentary.

Raw Arabic lines extracted from this frame:
{json.dumps(arabic_lines, ensure_ascii=False, indent=2)}
"""
    body = json.dumps(
        {
            "model": ANTHROPIC_MODEL,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        ANTHROPIC_API,
        data=body,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))

    text = result["content"][0]["text"].strip()
    return json.loads(text)


def main() -> None:
    require_env()

    state = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    hub = json.loads(JSON_FILE.read_text(encoding="utf-8")) if JSON_FILE.exists() else {}

    file_data = figma_get(f"/files/{FIGMA_FILE_KEY}")
    document = file_data["document"]

    ready_nodes: list = []
    find_ready_for_dev_nodes(document, ready_nodes)

    if not ready_nodes:
        print("No sections/frames currently marked Ready for Dev via Figma's real "
              "devStatus. Nothing to do.")
        return

    changed = False

    for node in ready_nodes:
        node_id = node["id"]
        texts: list = []
        collect_text(node, texts)
        if not texts:
            continue

        digest = content_hash(texts)
        if state.get(node_id) == digest:
            continue  # already synced in a previous run, content unchanged

        screen_key = to_screen_key(node["name"])
        print(f"New/updated Ready-for-Dev content in '{node['name']}' ({node_id}) -> {screen_key}")

        translated = call_claude_for_translation(node["name"], texts)

        hub.setdefault(screen_key, {})
        hub[screen_key].update(translated)

        state[node_id] = digest
        changed = True

    if changed:
        JSON_FILE.write_text(json.dumps(hub, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("localization_hub.json updated - the workflow will open a PR for review.")
    else:
        print("Ready-for-Dev sections found, but none have new or changed content since last sync.")


if __name__ == "__main__":
    main()
