#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 EXTENSION_ID" >&2
    exit 2
fi

extension_id=$1
script_directory=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repository_root=$(cd -- "$script_directory/.." && pwd)
native_host_path="$repository_root/native_host.py"
config_root=${XDG_CONFIG_HOME:-"$HOME/.config"}
data_root=${XDG_DATA_HOME:-"$HOME/.local/share"}
manifest_directory="$config_root/google-chrome/NativeMessagingHosts"
manifest_path="$manifest_directory/com.anyfiledownloader.native_host.json"
launcher_path="$data_root/anyfiledownloader/native_host_launcher.sh"

if ! command -v python3 >/dev/null 2>&1; then
    echo "python3 is required to install the native host manifest." >&2
    exit 1
fi

python3 "$repository_root/native_manifest.py" \
    --extension-id "$extension_id" \
    --host-path "$native_host_path" \
    --launcher-output "$launcher_path" \
    --output "$manifest_path"

echo "Installed Chrome native host manifest: $manifest_path"
echo "Installed native host launcher: $launcher_path"
echo "Allowed extension: chrome-extension://$extension_id/"
