#!/usr/bin/env bash
set -euo pipefail

config_root=${XDG_CONFIG_HOME:-"$HOME/.config"}
data_root=${XDG_DATA_HOME:-"$HOME/.local/share"}
manifest_path="$config_root/google-chrome/NativeMessagingHosts/com.anyfiledownloader.native_host.json"
launcher_path="$data_root/anyfiledownloader/native_host_launcher.sh"

if [[ -f "$manifest_path" ]]; then
    rm -- "$manifest_path"
    echo "Removed Chrome native host manifest: $manifest_path"
else
    echo "Chrome native host manifest is not installed: $manifest_path"
fi

if [[ -f "$launcher_path" ]]; then
    rm -- "$launcher_path"
    echo "Removed native host launcher: $launcher_path"
fi
