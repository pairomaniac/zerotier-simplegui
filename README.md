# ZeroTier SimpleGUI

A lightweight GTK4 interface for managing ZeroTier networks on Linux, with some gaming-focused niceties and a minimalistic look.

<img width="350" height="462" alt="Screenshot_20260518_224806" src="https://github.com/user-attachments/assets/9b7890eb-ffb4-4130-8582-c1dbccec5b7c" />


## Features

- View and manage ZeroTier networks
- Join/leave networks
- Monitor connected peers with latency
- Start/stop/restart the ZeroTier service
- Enable/disable service autostart
- Copy network IDs and IP addresses to clipboard
- Manual refresh button
- **Gaming optimizations:**
  - Broadcast route for LAN game discovery (255.255.255.255/32)
  - Automatic firewall zone configuration (firewalld/ufw)
  - Warm broadcast button to refresh broadcast on ZeroTier interfaces (helps Wine/Proton LAN discovery)
- Persistent settings via NetworkManager dispatcher
- Automatic theme detection (supports dark mode)
- Wayland and X11 support

## Requirements

- Linux desktop (systemd-based)
- GTK4 (4.10+) with Python bindings
- ZeroTier (zerotier-cli) installed and configured
- NetworkManager (optional, for dispatcher features)

## Installation

### Dependencies

**Debian-based:**
```bash
sudo apt install python3-gi gir1.2-gtk-4.0 zerotier-one
```

**Fedora-based:**
```bash
sudo dnf install python3-gobject gtk4 zerotier-one
```

**Arch-based:**
```bash
sudo pacman -S python-gobject gtk4 zerotier-one
```

### Install ZeroTier GUI

```bash
# Clone or download the repository
git clone https://github.com/pairomaniac/zerotier-gui.git
cd zerotier-gui

# Run the installer (must use sudo as a regular user)
chmod +x zt-gui-installer.sh
sudo ./zt-gui-installer.sh
```

The installer will:
- Install the application to `~/.local/bin/zerotier-gui`
- Create a polkit policy for privilege escalation
- Add a desktop entry and icon
- Refresh system caches

### Uninstall

```bash
sudo ./zt-gui-installer.sh --uninstall
```

## Usage

Launch from your application menu or run:

```bash
zerotier-gui
```

The application will prompt for authentication via polkit since ZeroTier management requires root privileges.

### Command Line Options

```
zerotier-gui [OPTIONS]

Options:
  -h, --help      Show help message
  -v, --version   Show version
```

## Gaming Features

### Broadcast Route

Enables LAN game discovery over ZeroTier by adding a broadcast route (`255.255.255.255/32`) to the first ZeroTier interface. Required for games that use broadcast packets for server discovery.

### Trusted Firewall Zone

Automatically configures your firewall to allow all traffic on ZeroTier interfaces:
- **firewalld:** Adds interface to the `trusted` zone
- **ufw:** Allows all inbound/outbound traffic on the interface

Both settings persist across reboots via a NetworkManager dispatcher script.

### Warm Broadcast

One-shot button that sends a brief broadcast ping burst on each ZeroTier interface. Useful before launching Wine/Proton LAN games when broadcast-based game discovery isn't working — the interface activity refreshes broadcast/multicast subscriptions on the ZeroTier side, which Wine sometimes fails to register on its own.

## How It Works

1. The application runs as root via `pkexec` (PolicyKit)
2. Display environment variables are passed through for GUI rendering
3. System theme is detected and applied
4. ZeroTier CLI commands are executed to manage networks
5. Dispatcher scripts handle persistent network configuration

## File Locations

| File | Purpose |
|------|---------|
| `~/.local/bin/zerotier-gui` | Main application |
| `~/.local/share/applications/com.local.zerotier-gui.desktop` | Desktop entry |
| `~/.local/share/icons/hicolor/scalable/apps/zerotier-gui.svg` | Application icon |
| `/etc/polkit-1/actions/com.local.zerotier-gui.policy` or `/usr/share/polkit-1/actions/com.local.zerotier-gui.policy` | PolicyKit policy |
| `/etc/NetworkManager/dispatcher.d/99-zerotier-gaming` | Persistent settings (created when enabled) |

## Troubleshooting

### NetworkManager features disabled

The broadcast route and firewall options require NetworkManager. If you're using a different network manager, these features won't be available through the GUI.

### Theme not applied

The application attempts to detect your GTK theme via gsettings. If detection fails, you can set it manually:
```bash
GTK_THEME=Adwaita:dark zerotier-gui
```

## Security Notes

- The application requires root privileges to manage ZeroTier
- Authentication is handled via PolicyKit (pkexec)
- Environment variables passed through pkexec are whitelisted
- Dispatcher scripts validate interface names before applying rules

## AI Disclaimer

This script was made with AI assistance.
