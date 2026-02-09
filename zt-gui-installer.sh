#!/bin/bash
# ZeroTier GUI Installer - installs zerotier-gui.py with polkit integration
set -euo pipefail

VERSION="1.1.0"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_SRC="$SCRIPT_DIR/zerotier-gui.py"

# --- Help and version ---
case "${1:-}" in
    -h|--help)
        cat << 'EOF'
ZeroTier GUI Installer

Usage: sudo ./zt-gui-installer.sh [OPTION]

Options:
  -h, --help      Show this help message
  -v, --version   Show version
  --uninstall     Remove ZeroTier GUI and all associated files

Requirements:
  - Run with sudo (as regular user, not root)
  - zerotier-gui.py must be in the same directory
  - Python 3.8+ with GTK4 bindings
  - NetworkManager (optional, for dispatcher features)
EOF
        exit 0 ;;
    -v|--version) echo "zt-gui-installer $VERSION"; exit 0 ;;
    --uninstall|"") ;;
    *) echo "Error: Unknown option '$1'. Use --help for usage." >&2; exit 1 ;;
esac

# --- Validation ---
[[ "$EUID" -ne 0 ]] && { echo "Error: Run with sudo" >&2; exit 1; }
[[ -z "${SUDO_USER:-}" || "$SUDO_USER" == "root" ]] && { echo "Error: Run as regular user with sudo" >&2; exit 1; }

USER_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
[[ ! -d "$USER_HOME" ]] && { echo "Error: Home directory not found" >&2; exit 1; }

# --- Paths ---
INSTALL_PATH="$USER_HOME/.local/bin/zerotier-gui"
DESKTOP_PATH="$USER_HOME/.local/share/applications/zerotier-gui.desktop"
ICON_PATH="$USER_HOME/.local/share/icons/hicolor/scalable/apps/zerotier-gui.svg"
DISPATCHER_PATH="/etc/NetworkManager/dispatcher.d/99-zerotier-gaming"

# Detect polkit actions directory (Fedora 43+ uses /usr/share, older distros use /etc)
detect_polkit_dir() {
    # Prefer /etc (works on immutable distros with read-only /usr)
    if [[ -d /etc/polkit-1/actions ]]; then
        echo "/etc/polkit-1/actions"
    elif [[ -d /usr/share/polkit-1/actions ]]; then
        echo "/usr/share/polkit-1/actions"
    else
        return 1
    fi
}

POLKIT_POLICY="com.local.zerotier-gui.policy"

# --- Helper: refresh system caches ---
refresh_caches() {
    echo "Refreshing caches..."
    
    # Reload polkit
    if systemctl is-active --quiet polkit 2>/dev/null; then
        systemctl restart polkit && echo "  * polkit"
    fi
    
    # Update icon cache
    if command -v gtk-update-icon-cache &>/dev/null; then
        gtk-update-icon-cache "$USER_HOME/.local/share/icons/hicolor/" 2>/dev/null || true
    elif [[ -x /usr/bin/gtk-update-icon-cache ]]; then
        /usr/bin/gtk-update-icon-cache "$USER_HOME/.local/share/icons/hicolor/" 2>/dev/null || true
    fi
    
    # KDE cache refresh
    if command -v kbuildsycoca6 &>/dev/null; then
        kbuildsycoca6 --noincremental 2>/dev/null || true
    elif command -v kbuildsycoca5 &>/dev/null; then
        kbuildsycoca5 --noincremental 2>/dev/null || true
    fi
    
    # Desktop database
    if command -v update-desktop-database &>/dev/null; then
        update-desktop-database "$USER_HOME/.local/share/applications" 2>/dev/null || true
    fi
}

# --- Uninstall ---
if [[ "${1:-}" == "--uninstall" ]]; then
    found=false
    echo "Uninstalling ZeroTier GUI..."
    echo ""
    
    for f in "$INSTALL_PATH" "$DESKTOP_PATH" "$ICON_PATH" "$DISPATCHER_PATH"; do
        if [[ -f "$f" ]]; then
            rm -f "$f"
            echo "  [x] $f"
            found=true
        fi
    done
    
    # Remove polkit policy from whichever location it exists
    for polkit_dir in /usr/share/polkit-1/actions /etc/polkit-1/actions; do
        f="$polkit_dir/$POLKIT_POLICY"
        if [[ -f "$f" ]]; then
            rm -f "$f"
            echo "  [x] $f"
            found=true
        fi
    done
    
    if [[ "$found" == true ]]; then
        echo ""
        refresh_caches
        echo ""
        echo "Done."
    else
        echo "Nothing to uninstall."
    fi
    exit 0
fi

# --- Pre-install checks ---
[[ ! -f "$PYTHON_SRC" ]] && { echo "Error: zerotier-gui.py not found in $SCRIPT_DIR" >&2; exit 1; }

# Verify it's a Python script (CRLF-tolerant)
head -1 "$PYTHON_SRC" | tr -d '\r' | grep -q '^#!/.*python' || { echo "Error: $PYTHON_SRC does not appear to be a Python script" >&2; exit 1; }

# Check Python version (3.8+)
if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" 2>/dev/null; then
    echo "Error: Python 3.8 or later required" >&2
    python3 --version 2>/dev/null || echo "Python 3 not found"
    exit 1
fi

# Check for iproute2
if ! command -v ip &>/dev/null; then
    echo "Error: 'ip' command not found. Install iproute2:" >&2
    command -v apt &>/dev/null && echo "  sudo apt install iproute2" >&2
    command -v dnf &>/dev/null && echo "  sudo dnf install iproute" >&2
    command -v pacman &>/dev/null && echo "  sudo pacman -S iproute2" >&2
    exit 1
fi

# Check for GTK4
if ! python3 -c "import gi; gi.require_version('Gtk', '4.0')" 2>/dev/null; then
    echo "Error: GTK4 Python bindings not found. Install with:" >&2
    command -v apt &>/dev/null && echo "  sudo apt install python3-gi gir1.2-gtk-4.0" >&2
    command -v dnf &>/dev/null && echo "  sudo dnf install python3-gobject gtk4" >&2
    command -v pacman &>/dev/null && echo "  sudo pacman -S python-gobject gtk4" >&2
    exit 1
fi

# Check for NetworkManager (optional)
if ! systemctl is-active --quiet NetworkManager 2>/dev/null; then
    echo "Note: NetworkManager not active. Dispatcher features (broadcast route,"
    echo "      firewall zone) will be disabled in the GUI."
    echo ""
fi

# Detect polkit directory
if ! POLKIT_DIR=$(detect_polkit_dir); then
    echo "Error: No polkit actions directory found (/usr/share/polkit-1/actions or /etc/polkit-1/actions)" >&2
    exit 1
fi
POLKIT_PATH="$POLKIT_DIR/$POLKIT_POLICY"

# --- Install ---
mkdir -p "$USER_HOME/.local/bin" "$USER_HOME/.local/share/applications" \
         "$USER_HOME/.local/share/icons/hicolor/scalable/apps"

echo "Installing ZeroTier GUI..."
echo ""

# Install main script
echo "  -> $INSTALL_PATH"
install -m 755 -o "$SUDO_USER" -g "$SUDO_USER" "$PYTHON_SRC" "$INSTALL_PATH"

# Install polkit policy
echo "  -> $POLKIT_PATH"
cat > "$POLKIT_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE policyconfig PUBLIC "-//freedesktop//DTD PolicyKit Policy Configuration 1.0//EN" "http://www.freedesktop.org/standards/PolicyKit/1/policyconfig.dtd">
<policyconfig>
  <action id="com.local.zerotier-gui.run">
    <description>Run ZeroTier GUI</description>
    <message>Authentication is required to manage ZeroTier</message>
    <defaults><allow_any>auth_admin</allow_any><allow_inactive>auth_admin</allow_inactive><allow_active>auth_admin</allow_active></defaults>
    <annotate key="org.freedesktop.policykit.exec.path">$INSTALL_PATH</annotate>
    <annotate key="org.freedesktop.policykit.exec.allow_gui">true</annotate>
  </action>
</policyconfig>
EOF
chmod 644 "$POLKIT_PATH"

# Install icon
echo "  -> $ICON_PATH"
cat > "$ICON_PATH" << 'ICON'
<svg xmlns="http://www.w3.org/2000/svg" width="78" height="78" viewBox="0 0 78 78" fill="none"><path d="M39 0C47.91 0 55.16 0.41 60.76 0.93C64.54 1.28 66.43 1.46 69.19 3C71.09 4.06 73.94 6.91 74.99 8.8C76.53 11.56 76.71 13.45 77.06 17.23C77.58 22.83 77.99 30.09 77.99 38.99C77.99 47.89 77.58 55.15 77.06 60.75C76.71 64.53 76.53 66.42 74.99 69.18C73.93 71.08 71.08 73.93 69.19 74.98C66.43 76.52 64.54 76.7 60.76 77.05C55.16 77.57 47.9 77.98 39 77.98C30.1 77.98 22.84 77.57 17.24 77.05C13.46 76.7 11.57 76.52 8.81001 74.98C6.91001 73.92 4.06001 71.07 3.01001 69.18C1.47001 66.42 1.29001 64.53 0.94001 60.75C0.42001 55.15 0.0100098 47.89 0.0100098 38.99C0.0100098 30.09 0.42001 22.83 0.94001 17.23C1.29001 13.45 1.47001 11.56 3.01001 8.8C4.07001 6.9 6.92001 4.05 8.81001 3C11.57 1.46 13.46 1.28 17.24 0.93C22.84 0.41 30.1 0 39 0ZM15 12C13.34 12 12 13.34 12 15C12 16.66 13.34 18 15 18H36V27.3C29.15 28.69 24 34.74 24 42C24 49.26 29.15 55.31 36 56.7V66C36 67.66 37.34 69 39 69C40.66 69 42 67.66 42 66V56.7C48.85 55.31 54 49.26 54 42C54 34.74 48.85 28.69 42 27.3V18H63C64.66 18 66 16.66 66 15C66 13.34 64.66 12 63 12H15ZM39 33C43.97 33 48 37.03 48 42C48 46.97 43.97 51 39 51C34.03 51 30 46.97 30 42C30 37.03 34.03 33 39 33Z" fill="#FFB25B"/></svg>
ICON
chown "$SUDO_USER:$SUDO_USER" "$ICON_PATH"

# Install desktop entry
echo "  -> $DESKTOP_PATH"
cat > "$DESKTOP_PATH" << EOF
[Desktop Entry]
Name=ZeroTier
Comment=ZeroTier Network Manager
Exec=$INSTALL_PATH
Icon=zerotier-gui
Terminal=false
Type=Application
Categories=Network;
EOF
chown "$SUDO_USER:$SUDO_USER" "$DESKTOP_PATH"

# --- Refresh system caches ---
echo ""
refresh_caches
echo ""
echo "Done. Run 'zerotier-gui' or find ZeroTier in your app menu."
echo "To uninstall: sudo $0 --uninstall"
