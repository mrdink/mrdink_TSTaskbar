#!/usr/bin/env python3
"""Minimal Tailscale status / connection toggle for KDE Plasma (Qt 6)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


REFRESH_MS = 5_000
STATUS_TIMEOUT_MS = 3_500
ACTION_TIMEOUT_MS = 30_000
SERVICE_START_TIMEOUT_MS = 120_000  # Allow time for graphical authorization.
POST_START_CHECK_TIMEOUT_SECONDS = 30
# On Arch Linux and CachyOS, tailscale is provided at this fixed, root-owned path.
# Do not resolve the command through PATH (which may contain untrusted directories).
TAILSCALE_EXECUTABLE = "/usr/bin/tailscale"
SYSTEMCTL_EXECUTABLE = "/usr/bin/systemctl"
TAILSCALED_UNIT = "tailscaled.service"


def tailscale_binary_available() -> bool:
    """Check the fixed executable path without searching the user's PATH."""
    return Path(TAILSCALE_EXECUTABLE).is_file() and os.access(TAILSCALE_EXECUTABLE, os.X_OK)


def daemon_start_action(state: str) -> str | None:
    """A stopped or failed daemon may be started; never guess on unknown states."""
    return "start" if state in ("inactive", "failed") else None


def post_daemon_start_action(raw: bytes | str) -> str | None:
    """Only bring up Tailscale if a freshly queried daemon reports Stopped."""
    return "up" if parse_status(raw).get("BackendState") == "Stopped" else None


def parse_status(raw: bytes | str) -> dict:
    """Return Tailscale's JSON object, or an empty dict when unavailable."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def classify_status(raw: bytes | str) -> tuple[bool, str, str]:
    """Parse `tailscale status --json` into (connected, readable status, IP)."""
    data = parse_status(raw)
    state = data.get("BackendState")
    messages = {
        "Running": "Connected",
        "Stopped": "Disconnected",
        "Starting": "Starting",
        "NeedsLogin": "Login required",
        "NeedsMachineAuth": "Device approval required",
        "NoState": "Status unavailable",
    }
    label = messages.get(state, "Status unavailable")
    if isinstance(state, str) and state and state not in messages:
        label = f"Disconnected ({state})"

    node = data.get("Self")
    ips = node.get("TailscaleIPs", []) if isinstance(node, dict) else []
    ip = ips[0] if isinstance(ips, list) and ips and isinstance(ips[0], str) else ""
    return state == "Running", label, ip


def action_for_status(raw: bytes | str) -> str | None:
    """Only toggle when the daemon confirms Running or Stopped.

    An unavailable status is *not* proof that Tailscale is down.
    """
    state = parse_status(raw).get("BackendState")
    return {"Running": "down", "Stopped": "up"}.get(state)


def visible_devices(raw: bytes | str) -> tuple[dict | None, list[dict]]:
    """Extract this device and peers from tailscale status --json.

    Only devices visible to this node under tailnet policy are returned.
    """
    data = parse_status(raw)
    if data.get("BackendState") != "Running":
        return None, []

    def normalize(node: object) -> dict | None:
        if not isinstance(node, dict):
            return None
        ips = node.get("TailscaleIPs")
        ips = [ip for ip in ips if isinstance(ip, str)] if isinstance(ips, list) else []
        dns = node.get("DNSName") if isinstance(node.get("DNSName"), str) else ""
        hostname = node.get("HostName") if isinstance(node.get("HostName"), str) else ""
        name = hostname or dns.rstrip(".").split(".")[0] or "Unnamed device"
        online = node.get("Online")
        return {
            "name": name,
            "dns": dns.rstrip("."),
            "ips": ips,
            "os": node.get("OS") if isinstance(node.get("OS"), str) else "",
            "online": online if isinstance(online, bool) else None,
            "active": node.get("Active") is True,
            "relay": node.get("Relay") if isinstance(node.get("Relay"), str) else "",
            "address": node.get("CurAddr") if isinstance(node.get("CurAddr"), str) else "",
        }

    local = normalize(data.get("Self"))
    peers_raw = data.get("Peer")
    peers = []
    if isinstance(peers_raw, dict):
        for item in peers_raw.values():
            peer = normalize(item)
            if peer is not None:
                peers.append(peer)
    peers.sort(key=lambda peer: (peer["online"] is not True, peer["name"].casefold()))
    return local, peers


def find_icon(filename: str) -> Path:
    """Find an icon when launched from source, locally installed, or packaged."""
    this_dir = Path(__file__).resolve().parent
    locations = (
        this_dir.parent / "assets",
        Path.home() / ".local/share/tailscale-t-indicator/assets",
        Path("/usr/share/tailscale-t-indicator/assets"),
    )
    for directory in locations:
        candidate = directory / filename
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Missing {filename}; looked in: {locations}")


def main() -> int:
    try:
        from PySide6.QtCore import QProcess, QTimer
        from PySide6.QtGui import QAction, QIcon
        from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
    except ImportError:
        print("Missing Qt dependency. Install it with: sudo pacman -S pyside6", file=sys.stderr)
        return 1

    # IMPORTANT: Create QApplication before QIcon / QPixmap objects.
    app = QApplication(sys.argv)
    app.setApplicationName("Tailscale T Indicator")
    app.setQuitOnLastWindowClosed(False)

    try:
        icon_up = QIcon(str(find_icon("t-up.png")))
        icon_down = QIcon(str(find_icon("t-down.png")))
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    class Indicator:
        def __init__(self) -> None:
            self.connected = False
            self.next_action: str | None = None
            self.active_action: str | None = None
            self.action_timed_out = False
            self.device_snapshot = b""
            self.status_phase = "service"
            self.status_timed_out = False
            self.connect_after_start = False
            self.connect_after_start_deadline = 0.0

            self.tray = QSystemTrayIcon(icon_down, app)
            self.tray.setToolTip("Tailscale: Checking status")

            menu = QMenu()
            self.status_action = QAction("Checking status…", menu)
            self.status_action.setEnabled(False)
            menu.addAction(self.status_action)
            self.device_info = menu.addAction("This device: unavailable")
            self.device_info.setEnabled(False)
            self.devices_menu = menu.addMenu("Devices")
            self.devices_menu.aboutToShow.connect(self.populate_devices)
            self.toggle_action = menu.addAction("Connect / Disconnect")
            self.toggle_action.setEnabled(False)
            self.toggle_action.triggered.connect(self.toggle)
            menu.addSeparator()
            refresh_action = menu.addAction("Refresh status")
            refresh_action.triggered.connect(self.refresh)
            menu.addSeparator()
            quit_action = menu.addAction("Quit indicator")
            quit_action.triggered.connect(app.quit)
            self.tray.setContextMenu(menu)

            # Separate processes so a pending status poll cannot collide with a toggle.
            self.status_process = QProcess(app)
            self.status_process.finished.connect(self.on_status_finished)
            self.status_process.errorOccurred.connect(self.on_status_error)
            self.status_timeout = QTimer(app)
            self.status_timeout.setSingleShot(True)
            self.status_timeout.timeout.connect(self.on_status_timeout)

            self.action_process = QProcess(app)
            self.action_process.finished.connect(self.on_action_finished)
            self.action_process.errorOccurred.connect(self.on_action_error)
            self.action_timeout = QTimer(app)
            self.action_timeout.setSingleShot(True)
            self.action_timeout.timeout.connect(self.on_action_timeout)

            self.poller = QTimer(app)
            self.poller.setInterval(REFRESH_MS)
            self.poller.timeout.connect(self.refresh)
            self.poller.start()

            self.tray.activated.connect(self.on_activate)
            app.aboutToQuit.connect(self.on_quit)
            self.tray.show()
            self.refresh()

        def show_status(self, connected: bool, label: str, ip: str = "", action: str | None = None) -> None:
            if not connected:
                self.device_snapshot = b""
                self.device_info.setText("This device: unavailable")
                self.device_info.setToolTip("")
            self.connected = connected
            self.next_action = action
            self.tray.setIcon(icon_up if connected else icon_down)
            self.status_action.setText(label)
            tooltip = f"Tailscale: {label}"
            if connected and ip:
                tooltip += f"\nIP: {ip}"
            if action is not None and self.active_action is None:
                tooltip += ("\nLeft-click to start the Tailscale service" if action == "start" else
                            "\nLeft-click to connect" if action == "up" else
                            "\nLeft-click to disconnect")
            self.tray.setToolTip(tooltip)
            self.toggle_action.setEnabled(action is not None and self.active_action is None)
            self.toggle_action.setText("Start Tailscale service" if action == "start" else
                                       "Connect Tailscale" if action == "up" else
                                       "Disconnect Tailscale" if action == "down" else
                                       "Connect / Disconnect (status unavailable)")


        def populate_devices(self) -> None:
            """Build the peer menu on opening, not during the status polling timer."""
            self.devices_menu.clear()
            local, peers = visible_devices(self.device_snapshot)
            if local is None:
                action = self.devices_menu.addAction("Device list unavailable while disconnected")
                action.setEnabled(False)
                return

            if not peers:
                empty = self.devices_menu.addAction("No visible peers")
                empty.setEnabled(False)
                return

            online_count = sum(peer["online"] is True for peer in peers)
            header = self.devices_menu.addAction(f"{online_count} online / {len(peers)} visible")
            header.setEnabled(False)
            self.devices_menu.addSeparator()
            for peer in peers:
                state = "●" if peer["online"] is True else ("○" if peer["online"] is False else "?")
                ip = peer["ips"][0] if peer["ips"] else "No Tailscale IP"
                submenu = self.devices_menu.addMenu(f"{state} {peer['name']}  —  {ip}")
                status = "Online" if peer["online"] is True else ("Offline" if peer["online"] is False else "Unknown")
                title = submenu.addAction(f"Status: {status}")
                title.setEnabled(False)
                if peer["os"]:
                    os_action = submenu.addAction(f"OS: {peer['os']}")
                    os_action.setEnabled(False)
                if peer["address"] and peer["active"]:
                    direct = submenu.addAction(f"Connection: direct ({peer['address']})")
                    direct.setEnabled(False)
                elif peer["relay"] and peer["active"]:
                    relay = submenu.addAction(f"Connection: relay ({peer['relay']})")
                    relay.setEnabled(False)
                submenu.addSeparator()
                for ip_address in peer["ips"]:
                    action = submenu.addAction(f"Copy IP: {ip_address}")
                    action.triggered.connect(
                        lambda checked=False, value=ip_address: QApplication.clipboard().setText(value)
                    )
                if peer["dns"]:
                    action = submenu.addAction(f"Copy MagicDNS: {peer['dns']}")
                    action.triggered.connect(
                        lambda checked=False, value=peer["dns"]: QApplication.clipboard().setText(value)
                    )

        def refresh(self) -> None:
            if self.active_action is not None:
                return
            if self.status_process.state() != QProcess.ProcessState.NotRunning:
                return
            if not Path(SYSTEMCTL_EXECUTABLE).is_file():
                self.show_status(False, "systemctl not found")
                return

            # Always check the system service *before* asking the Tailscale CLI.
            self.status_phase = "service"
            self.status_timed_out = False
            self.status_process.start(SYSTEMCTL_EXECUTABLE, ["is-active", TAILSCALED_UNIT])
            self.status_timeout.start(STATUS_TIMEOUT_MS)

        def on_status_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
            self.status_timeout.stop()
            if self.active_action is not None or self.status_timed_out:
                return  # Ignore stale status while changing the connection.
            if exit_status != QProcess.ExitStatus.NormalExit:
                self.show_status(False, "Status command failed")
                return

            output = bytes(self.status_process.readAllStandardOutput())
            if self.status_phase == "service":
                state = output.decode("utf-8", errors="replace").strip()
                if state == "active":
                    if not tailscale_binary_available():
                        self.show_status(False, "Tailscale CLI not found")
                        self.connect_after_start = False
                        return
                    self.status_phase = "tailscale"
                    self.status_timed_out = False
                    self.status_process.start(TAILSCALE_EXECUTABLE, ["status", "--json"])
                    self.status_timeout.start(STATUS_TIMEOUT_MS)
                    return

                if self.connect_after_start:
                    if state != "activating" or time.monotonic() >= self.connect_after_start_deadline:
                        self.connect_after_start = False
                        self.notify_error("Tailscale service did not become active.")
                if state == "activating":
                    self.show_status(False, "Tailscale service starting")
                elif daemon_start_action(state) is not None:
                    self.show_status(False, "Tailscale service stopped", action="start")
                else:
                    # Unknown, missing, and deactivating are *not* proof it is safe to start.
                    self.show_status(False, "Tailscale service status unavailable")
                return

            # The CLI JSON can be meaningful even if tailscale exits nonzero.
            connected, label, ip = classify_status(output)
            self.device_snapshot = output
            local, peers = visible_devices(output)
            if local is not None:
                ip_text = ", ".join(local["ips"]) if local["ips"] else "No IP"
                self.device_info.setText(f"This device: {local['name']} — {ip_text}")
                self.device_info.setToolTip(local["dns"])
            else:
                self.device_info.setText("This device: unavailable")
                self.device_info.setToolTip("")
            self.show_status(connected, label, ip, action_for_status(output))

            if self.connect_after_start:
                state = parse_status(output).get("BackendState")
                if state == "Running":
                    # tailscaled restored its previous connection automatically.
                    self.connect_after_start = False
                elif post_daemon_start_action(output) == "up":
                    self.connect_after_start = False
                    self.start_action("up")
                elif state in ("NeedsLogin", "NeedsMachineAuth"):
                    self.connect_after_start = False
                    self.notify_error("Service started; Tailscale needs login or device approval.")
                elif time.monotonic() >= self.connect_after_start_deadline:
                    self.connect_after_start = False
                    self.notify_error("Service started, but Tailscale did not report a ready state.")

        def on_status_error(self, error: QProcess.ProcessError) -> None:
            if error == QProcess.ProcessError.FailedToStart:
                self.status_timeout.stop()
                if self.active_action is None:
                    self.show_status(False, "Cannot start status command")

        def on_status_timeout(self) -> None:
            self.status_timed_out = True
            self.show_status(False, "Status check timed out")
            if self.status_process.state() != QProcess.ProcessState.NotRunning:
                self.status_process.kill()

        def on_activate(self, reason: QSystemTrayIcon.ActivationReason) -> None:
            if reason == QSystemTrayIcon.ActivationReason.Trigger:
                self.toggle()

        def toggle(self) -> None:
            if self.active_action is not None or self.next_action is None:
                return
            self.start_action(self.next_action)

        def start_action(self, command: str) -> None:
            """Run an allowed action, without a shell or a sudo password pipe."""
            if self.active_action is not None or command not in ("start", "up", "down"):
                return
            if command == "start":
                if not Path(SYSTEMCTL_EXECUTABLE).is_file():
                    self.notify_error("systemctl not found.")
                    return
            elif not tailscale_binary_available():
                self.show_status(False, "Tailscale CLI not found")
                return

            self.active_action = command
            self.action_timed_out = False
            if command == "start":
                self.show_status(False, "Starting Tailscale service…")
                # systemctl requests authorization through systemd/PolicyKit. KDE
                # can show its usual admin prompt, without invoking sudo or pkexec.
                self.action_process.start(SYSTEMCTL_EXECUTABLE, ["start", TAILSCALED_UNIT])
                self.action_timeout.start(SERVICE_START_TIMEOUT_MS)
            else:
                self.show_status(self.connected, "Connecting…" if command == "up" else "Disconnecting…")
                # Use Tailscale operator permission; never launch this app as root.
                self.action_process.start(TAILSCALE_EXECUTABLE, [command])
                self.action_timeout.start(ACTION_TIMEOUT_MS)

        def on_action_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
            self.action_timeout.stop()
            command = self.active_action
            self.active_action = None
            if command is None:
                return
            error = bytes(self.action_process.readAllStandardError()).decode("utf-8", errors="replace").strip()
            out = bytes(self.action_process.readAllStandardOutput()).decode("utf-8", errors="replace").strip()
            success = (not self.action_timed_out and
                       exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0)
            if success and command == "start":
                # Check the daemon and current Tailscale state again first. Do not
                # call 'tailscale up' when tailscaled already reconnected itself.
                self.connect_after_start = True
                self.connect_after_start_deadline = time.monotonic() + POST_START_CHECK_TIMEOUT_SECONDS
                self.refresh()
                return

            if self.action_timed_out:
                self.notify_error("Service start timed out." if command == "start" else
                                  "Connection change timed out. Check Tailscale in a terminal.")
            elif not success:
                detail = error or out or f"{command} exited with code {exit_code}"
                print(f"Tailscale {command} failed: {detail}", file=sys.stderr)
                if command == "start":
                    self.notify_error(("Unable to start tailscaled.service. " + detail)[:300])
                else:
                    hint = '\\nIf permission was denied: sudo tailscale set --operator="$USER"'
                    self.notify_error((detail[:250] + hint)
                                      if "permission" in detail.lower() or "access denied" in detail.lower()
                                      else detail[:300])
            self.refresh()

        def on_action_error(self, error: QProcess.ProcessError) -> None:
            if error == QProcess.ProcessError.FailedToStart:
                self.action_timeout.stop()
                command = self.active_action
                self.active_action = None
                self.notify_error("Cannot start systemctl." if command == "start" else
                                  "Cannot run Tailscale CLI.")
                self.refresh()

        def on_action_timeout(self) -> None:
            self.action_timed_out = True
            if self.action_process.state() != QProcess.ProcessState.NotRunning:
                self.action_process.kill()

        def notify_error(self, message: str) -> None:
            self.tray.showMessage("Tailscale action failed", message,
                                  QSystemTrayIcon.MessageIcon.Warning, 7000)

        def on_quit(self) -> None:
            self.poller.stop()
            self.status_timeout.stop()
            self.action_timeout.stop()
            for process in (self.status_process, self.action_process):
                if process.state() != QProcess.ProcessState.NotRunning:
                    process.kill()
                    process.waitForFinished(200)

    indicator = Indicator()  # Keep the object alive throughout the Qt event loop.
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
