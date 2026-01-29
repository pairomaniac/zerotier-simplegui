# ZeroTier SimpleGUI

A lightweight GTK4 interface for managing ZeroTier networks on Linux, with some gaming-focused niceties and a minimalistic look.

<img width="307" height="367" alt="zt-gaming" src="https://github.com/user-attachments/assets/3a9f6b17-b62e-4777-9d79-ae85648f0b51" />

## Features

- View and manage ZeroTier networks
- Join/leave networks
- Monitor connected peers with latency
- Start/stop/restart the ZeroTier service
- Enable/disable service autostart
- Copy network IP addresses to clipboard
- **Gaming optimizations:**
  - Broadcast route for LAN game discovery (255.255.255.255/32)
  - Automatic firewall zone configuration (firewalld/ufw)
- Persistent settings via NetworkManager dispatcher
- Automatic theme detection (supports dark mode)
- Wayland and X11 support

## Requirements

- Linux with systemd (most desktop distros)
- Python 3.8+
- GTK4 with Python bindings
- ZeroTier (zerotier-cli) installed and configured
- PolicyKit (polkit) for privilege escalation
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
git clone https://github.com/yourusername/zerotier-gui.git
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
sudo ./zt-gui-installer.sh uninstall
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

Enables LAN game discovery over ZeroTier by adding a broadcast route (`255.255.255.255/32`) to the ZeroTier interface. Required for games that use broadcast packets for server discovery.

### Trusted Firewall Zone

Automatically configures your firewall to allow all traffic on ZeroTier interfaces:
- **firewalld:** Adds interface to the `trusted` zone
- **ufw:** Allows all inbound/outbound traffic on the interface

Both settings persist across reboots via a NetworkManager dispatcher script.

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
| `~/.local/share/applications/zerotier-gui.desktop` | Desktop entry |
| `~/.local/share/icons/hicolor/scalable/apps/zerotier-gui.svg` | Application icon |
| `/etc/polkit-1/actions/com.local.zerotier-gui.policy` | PolicyKit policy |
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
