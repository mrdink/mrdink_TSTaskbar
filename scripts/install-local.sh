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
    # Use exactly one autostart mechanism (systemd user service, not KDE XDG).
    install -d "$HOME/.config/systemd/user"
    install -m 644 "$ROOT/systemd/tailscale-t-indicator.service" \
        "$HOME/.config/systemd/user/tailscale-t-indicator.service"
    rm -f "$HOME/.config/autostart/tailscale-t-indicator.desktop" \
          "$HOME/.config/autostart/tailscale-t-indicator.desktop.disabled"
    systemctl --user daemon-reload
    systemctl --user enable tailscale-t-indicator.service
    # If the service is already running, apply the update immediately.
    if systemctl --user is-active --quiet tailscale-t-indicator.service; then
        systemctl --user restart tailscale-t-indicator.service
    fi
    echo "Enabled a single autostart mechanism: systemd user service."
    echo "If currently running from python or gtk-launch, quit that copy."
    echo "Start with: systemctl --user start tailscale-t-indicator.service"
fi
echo "Installed to ~/.local/bin/tailscale-t-indicator"
echo "Start it with: ~/.local/bin/tailscale-t-indicator"
echo "To enable login startup: bash scripts/install-local.sh --autostart"
