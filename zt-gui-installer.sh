#!/bin/bash
# ZeroTier GUI Installer - installs zerotier-gui.py with polkit integration
set -euo pipefail

VERSION="1.0.0"
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
  uninstall       Remove ZeroTier GUI and all associated files

Requirements:
  - Run with sudo (as regular user, not root)
  - zerotier-gui.py must be in the same directory
  - Python 3.8+ with GTK4 bindings
  - NetworkManager (optional, for dispatcher features)
EOF
        exit 0 ;;
    -v|--version) echo "zt-gui-installer $VERSION"; exit 0 ;;
    uninstall|"") ;;
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
POLKIT_PATH="/etc/polkit-1/actions/com.local.zerotier-gui.policy"
DISPATCHER_PATH="/etc/NetworkManager/dispatcher.d/99-zerotier-gaming"

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
if [[ "${1:-}" == "uninstall" ]]; then
    found=false
    echo "Uninstalling ZeroTier GUI..."
    echo ""
    
    for f in "$INSTALL_PATH" "$POLKIT_PATH" "$DESKTOP_PATH" "$ICON_PATH" "$DISPATCHER_PATH"; do
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

# Verify it's a Python script
head -1 "$PYTHON_SRC" | grep -q '^#!/.*python' || { echo "Error: $PYTHON_SRC does not appear to be a Python script" >&2; exit 1; }

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
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><rect width="100" height="100" rx="18" fill="#ffb441"/><line x1="14" y1="17" x2="86" y2="17" stroke="#1a1a1a" stroke-width="4"/><line x1="50" y1="17" x2="50" y2="88" stroke="#1a1a1a" stroke-width="4"/><circle cx="50" cy="55" r="24" fill="none" stroke="#1a1a1a" stroke-width="4"/></svg>
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
echo "To uninstall: sudo $0 uninstall"
