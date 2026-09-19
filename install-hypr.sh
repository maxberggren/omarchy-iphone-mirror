#!/usr/bin/env bash
# Install the Hyprland side of this fork: the drag-up-from-below-the-window
# Home gesture. Keybindings are not installed. Safe to run again.
set -euo pipefail

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
hypr_dir=${XDG_CONFIG_HOME:-"$HOME/.config"}/hypr
main="$hypr_dir/hyprland.lua"

if [[ ! -f $main ]]; then
  printf 'iphone-mirror: %s not found; this needs Omarchy with the Lua Hyprland config\n' "$main" >&2
  exit 1
fi

install -m 0644 "$source_dir/hypr/iphone-mirror.lua" "$hypr_dir/iphone-mirror.lua"
if ! grep -q 'require("hypr.iphone-mirror")' "$main"; then
  cp "$main" "$main.bak.$(date +%s)"
  printf '\n-- iPhone Mirror Home drag gesture.\nrequire("hypr.iphone-mirror")\n' >> "$main"
fi

hyprctl reload >/dev/null
errors=$(hyprctl configerrors)
if [[ -n ${errors//[[:space:]]/} ]]; then
  printf 'iphone-mirror: Hyprland reports config errors:\n%s\n' "$errors" >&2
  exit 1
fi
printf '%s\n' 'Hyprland integration installed: drag up from below the mirror window to press Home.'
