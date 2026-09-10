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
project_python="$repository_root/.venv/bin/python"
config_root=${XDG_CONFIG_HOME:-"$HOME/.config"}
data_root=${XDG_DATA_HOME:-"$HOME/.local/share"}
manifest_directory="$config_root/google-chrome/NativeMessagingHosts"
manifest_path="$manifest_directory/com.anyfiledownloader.native_host.json"
launcher_path="$data_root/anyfiledownloader/native_host_launcher.sh"

if [[ ! -x "$project_python" ]]; then
    echo "Project Python is missing: $project_python" >&2
    echo "Create .venv and install requirements before registering the native host." >&2
    exit 1
fi

"$project_python" "$repository_root/native_manifest.py" \
    --extension-id "$extension_id" \
    --host-path "$native_host_path" \
    --launcher-output "$launcher_path" \
    --output "$manifest_path"

echo "Installed Chrome native host manifest: $manifest_path"
echo "Installed native host launcher: $launcher_path"
echo "Allowed extension: chrome-extension://$extension_id/"
