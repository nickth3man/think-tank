#!/bin/sh
# Install the loop skill from the repo into the agent's skill directory.
#
# The repo copy (workflows/deckgen-loop/SKILL.md) is the source of truth; this script makes
# the installed copy a derived artifact, so a fresh clone can restore it and a stale install
# can be refreshed. check_docs.py warns when the two differ.
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd)
src="$repo_root/workflows/deckgen-loop/SKILL.md"
dest_dir="${1:-$HOME/.omp/agent/skills/deckgen-loop}"

[ -f "$src" ] || { echo "missing source: $src" >&2; exit 1; }
mkdir -p "$dest_dir"
cp "$src" "$dest_dir/SKILL.md"
echo "installed $src -> $dest_dir/SKILL.md"
