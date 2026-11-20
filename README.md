# Tailscale T Indicator

A lightweight, **unofficial** Tailscale system-tray indicator for **CachyOS / Arch Linux** and KDE Plasma, written in Python and PySide6 (Qt 6).

- **White T** on a transparent background: Tailscale is up (`Running`).
- **Black T** on a transparent background: Tailscale is down, logged out, or unavailable.
- **Left-click** the T to toggle between `tailscale up` and `tailscale down`. If `tailscaled.service` is stopped, the same click starts that system service first, checks if Tailscale reconnected automatically, and runs `tailscale up` only if needed.
- **Right-click** for local device info, peer list (online/offline), OS, IPv4/IPv6, MagicDNS, connection method when known, one-click copy, refresh, connect/disconnect, and quit.
- Automatically refreshes status every **5 seconds**, with tooltip and error notifications.
- Optional **single systemd user-service autostart** at login (the installer removes its prior KDE autostart entry). No root privileges or password required to **run the app**.

> This is a community project, not associated with or endorsed by Tailscale Inc.

## Requirements

KDE Plasma (or another desktop with a system tray), Tailscale configured on your machine, Python 3, and PySide6/Qt 6.

For security, this Arch/CachyOS build invokes the Tailscale CLI using the fixed path `/usr/bin/tailscale`, not the user's `PATH`. If your distribution installs the binary elsewhere, adjust `TAILSCALE_EXECUTABLE` in the Python source.

On CachyOS / Arch Linux:

```bash
sudo pacman -S --needed python pyside6 tailscale git
```

## Important: Allow your user to toggle Tailscale

**You must authorize your account once** before left-click can connect/disconnect. Tailscale normally requires administrator permission to change its connection state, so the tray app intentionally does not invoke `sudo` or `pkexec` for CLI toggling. To start a stopped `tailscaled.service`, it runs `/usr/bin/systemctl start tailscaled.service`, requesting authorization from systemd/PolicyKit as needed. A working desktop authentication agent (normally provided by KDE Plasma) is required if your account is not authorized to start system services without a password. No sudoers rule or passwordless root access is installed.

Run this **once** in a terminal as the desktop user who will run the app:

```bash
sudo tailscale set --operator="$(whoami)"
```

Now test without `sudo`:

```bash
tailscale down
tailscale up
```

After that, clicking the T should toggle Tailscale without a password prompt. This grants the designated user permission to operate the **local Tailscale daemon**; only do this for users you trust. On shared computers, other users may each need authorization. This setting is **not** automatically applied by `pacman`, an AUR helper, or the local installer.

**Warning:** `tailscale down` disconnects active Tailscale connections, including any remote Tailscale SSH session you might be using. It does not stop `tailscaled` or log your account out. If `tailscale up` needs interactive sign-in or additional custom flags, complete that in the terminal first.

## Install from GitHub

```bash
git clone https://github.com/mrdink/mrdink_TSTaskbar.git
cd mrdink_TSTaskbar
bash scripts/install-local.sh --autostart
systemctl --user start tailscale-t-indicator.service
```

The `--autostart` installer uses the systemd **user** service only. It removes the older `~/.config/autostart/tailscale-t-indicator.desktop` entry to prevent two tray icons. It does not modify unrelated autostart files. It enables the service but doesn't launch a second process on top of a manually started one; close any manually started indicator before starting the service. The service starts after the graphical session with a five-second delay.

Check: `systemctl --user status tailscale-t-indicator.service`. Disable: `systemctl --user disable --now tailscale-t-indicator.service`.

To install *without* autostart, run `bash scripts/install-local.sh` instead. Everything goes into your home directory; the installer does not need root.

To test the app directly from the source directory without installing:

```bash
python src/tailscale_t_indicator.py
```

If you don't see the T in KDE Plasma, open **Configure System Tray → Entries** and set the indicator to **Always shown**.

To upgrade a local installation, `git pull` and rerun the installer. Right-click the running icon → **Quit indicator**, then restart with `~/.local/bin/tailscale-t-indicator`.

## AUR / pacman packaging

A draft Arch User Repository (AUR) **-git** package recipe is provided at [`packaging/PKGBUILD`](packaging/PKGBUILD). This repository being public on GitHub **does not by itself publish an AUR package**. After the recipe is tested and submitted separately to the AUR, an AUR helper such as `paru` can install it. Plain `pacman -S` does not access AUR packages.

To test the local AUR recipe:

```bash
cd packaging
makepkg -si
```

To prepare its separate AUR repository submission:

```bash
makepkg --printsrcinfo > .SRCINFO
```

## Testing and implementation

```bash
python -m unittest discover -s tests -v
```

Right-click device details come from the local `tailscale status --json` response. It lists only peers visible to this device, not necessarily the full tailnet. Online status and the current connection method may be unknown. Choosing an IP or MagicDNS item copies it to the clipboard; no privileged calls are used for this.

Before each Tailscale status poll, the app checks `/usr/bin/systemctl is-active tailscaled.service`. If the daemon is inactive or failed, the icon offers **Start Tailscale service**; clicking invokes systemctl and may show a KDE authorization dialog. After the daemon starts, the app waits for its status, leaves an automatically reconnected session alone, and calls `tailscale up` only if Tailscale explicitly reports `Stopped`. It never silently starts the service merely because the indicator launched. Unknown service/Tailscale states do not trigger a connection command. If authorization fails, check that KDE's polkit agent is running, or start the system service manually with `sudo systemctl start tailscaled.service`.

Normal connection changes still use the current user's `tailscale` CLI operator permission; the indicator itself remains unprivileged.

The editable vector icons are in `assets/`; the app uses transparent 64×64 PNGs. These custom T icons are **not** Tailscale's trademarked logo.

## License

GNU General Public License v3.0; see [LICENSE](LICENSE).
