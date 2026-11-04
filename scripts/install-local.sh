#!/usr/bin/env bash
# Install only into this user's home directory; no sudo required.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
install -d "$HOME/.local/bin" "$HOME/.local/lib/tailscale-t-indicator" \
           "$HOME/.local/share/tailscale-t-indicator/assets" \
           "$HOME/.local/share/applications"
install -m 755 "$ROOT/src/tailscale_t_indicator.py" \
    "$HOME/.local/lib/tailscale-t-indicator/tailscale_t_indicator.py"
install -m 644 "$ROOT/assets/t-up.png" "$ROOT/assets/t-down.png" \
    "$HOME/.local/share/tailscale-t-indicator/assets/"
cat > "$HOME/.local/bin/tailscale-t-indicator" <<EOF_WRAPPER
#!/bin/sh
exec /usr/bin/python "$HOME/.local/lib/tailscale-t-indicator/tailscale_t_indicator.py" "\$@"
EOF_WRAPPER
chmod 755 "$HOME/.local/bin/tailscale-t-indicator"
sed "s|^Exec=.*|Exec=$HOME/.local/bin/tailscale-t-indicator|" \
    "$ROOT/desktop/tailscale-t-indicator.desktop" \
    > "$HOME/.local/share/applications/tailscale-t-indicator.desktop"
if [[ "${1:-}" == "--autostart" ]]; then
    install -d "$HOME/.config/autostart"
    install -m 644 "$HOME/.local/share/applications/tailscale-t-indicator.desktop" \
        "$HOME/.config/autostart/tailscale-t-indicator.desktop"
fi
echo "Installed to ~/.local/bin/tailscale-t-indicator"
echo "Start it with: ~/.local/bin/tailscale-t-indicator"
echo "To enable login startup: bash scripts/install-local.sh --autostart"
