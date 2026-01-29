#!/usr/bin/env python3
"""ZeroTier GUI - A GTK4 interface for managing ZeroTier networks."""
import os
import sys
import subprocess
import time
import shutil
from concurrent.futures import ThreadPoolExecutor

VERSION = "1.0.0"
DISPATCHER_PATH = "/etc/NetworkManager/dispatcher.d/99-zerotier-gaming"
CMD_TIMEOUT = 5

# Whitelisted environment variables that can be passed through pkexec
ALLOWED_ENV = frozenset({
    'DISPLAY', 'WAYLAND_DISPLAY', 'USER_HOME',
    'GTK_A11Y', 'GTK_USE_PORTAL', 'GTK_THEME'
})

STATUS_COLORS = {
    'OK': '#2ecc71',
    'WARN': '#f39c12',
    'ACCESS_DENIED': '#f39c12',
    'REQUESTING_CONFIGURATION': '#f39c12'
}

# --- Argument parsing (before privilege escalation) ---
for arg in sys.argv[1:]:
    if arg in ('-h', '--help'):
        print(f"""ZeroTier GUI v{VERSION}

Usage: zerotier-gui [OPTIONS]

Options:
  -h, --help      Show this help message
  -v, --version   Show version

Requires root privileges (prompts via polkit) and zerotier-cli in PATH.""")
        sys.exit(0)
    elif arg in ('-v', '--version'):
        print(f"zerotier-gui {VERSION}")
        sys.exit(0)
    elif arg.startswith('-') and '=' not in arg:
        sys.exit(f"Error: Unknown option '{arg}'. Use --help for usage.")


def gsettings_get(key):
    """Get GNOME desktop setting."""
    try:
        r = subprocess.run(
            ['gsettings', 'get', 'org.gnome.desktop.interface', key],
            capture_output=True, text=True, timeout=CMD_TIMEOUT
        )
        return r.stdout.strip().strip("'") if r.returncode == 0 else ''
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ''


# --- Privilege escalation via pkexec ---
if os.geteuid() != 0:
    env = [f"USER_HOME={os.path.expanduser('~')}", "GTK_A11Y=none", "GTK_USE_PORTAL=0"]
    
    if 'DISPLAY' in os.environ:
        env.append(f"DISPLAY={os.environ['DISPLAY']}")
    
    xdg_runtime = os.environ.get('XDG_RUNTIME_DIR', '')
    wayland = os.environ.get('WAYLAND_DISPLAY', '')
    if xdg_runtime and wayland:
        if not wayland.startswith('/'):
            wayland = f"{xdg_runtime}/{wayland}"
        env.append(f"WAYLAND_DISPLAY={wayland}")
    
    # Detect and pass through theme
    if theme := gsettings_get('gtk-theme'):
        prefer_dark = 'dark' in gsettings_get('color-scheme').lower()
        if prefer_dark and not theme.lower().endswith('-dark'):
            theme = f"{theme}-Dark"
        env.append(f"GTK_THEME={theme}")
    
    os.execvp('pkexec', ['pkexec', sys.argv[0]] + env)

# Restore whitelisted env vars passed through pkexec
for a in sys.argv[1:]:
    if '=' in a:
        key, val = a.split('=', 1)
        if key in ALLOWED_ENV:
            os.environ[key] = val

# --- GTK imports (after privilege escalation) ---
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib, Gdk


class ZerotierGUI(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='com.local.zerotier-gui')
        self.has_systemd = None      # None = not yet checked
        self.has_nm = None           # NetworkManager available
        self.fw_type = None          # "firewalld", "ufw", or None
        self.busy = False
        self._exec = ThreadPoolExecutor(max_workers=4)
        self.connect('activate', self.on_activate)

    def cmd(self, *args, timeout=CMD_TIMEOUT):
        """Run command with timeout, return stdout or empty string on failure."""
        try:
            return subprocess.run(
                args, capture_output=True, text=True, timeout=timeout
            ).stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return ''

    def dot(self, status):
        """Return colored status dot markup."""
        return f'<span foreground="{STATUS_COLORS.get(status, "#e74c3c")}">●</span>'

    def set_status(self, status, text):
        """Update status label with colored dot."""
        self.status.set_markup(f'{self.dot(status)} <b>Status:</b> {text}')

    def clear_box(self, box):
        """Remove all children from a Gtk.Box."""
        while child := box.get_first_child():
            box.remove(child)

    def get_zt_ifaces(self):
        """Get all ZeroTier interface names from /sys/class/net."""
        try:
            return [e for e in os.listdir('/sys/class/net') if e.startswith('zt')]
        except OSError:
            return []

    def get_service_info(self):
        """Get service state and enabled status in one systemctl call.
        Returns: (active_state, is_enabled, cli_online)
        """
        cli_online = 'online' in self.cmd('zerotier-cli', 'info').lower()
        
        if not self.has_systemd:
            return ('unknown', False, cli_online)
        
        out = self.cmd('systemctl', 'show', 'zerotier-one',
                       '--property=ActiveState,UnitFileState')
        state, enabled = 'unknown', False
        for line in out.split('\n'):
            if line.startswith('ActiveState='):
                state = line.split('=', 1)[1]
            elif line.startswith('UnitFileState='):
                enabled = line.split('=', 1)[1] == 'enabled'
        return (state, enabled, cli_online)

    def detect_firewall(self):
        """Detect active firewall type."""
        if shutil.which('firewall-cmd'):
            if self.cmd('systemctl', 'is-active', 'firewalld') == "active":
                return "firewalld"
        if shutil.which('ufw'):
            if "Status: active" in self.cmd('ufw', 'status'):
                return "ufw"
        return None

    # --- Dispatcher script for persistent route/firewall settings ---
    def read_dispatcher(self):
        """Read current dispatcher script state. Returns (route_enabled, fw_enabled)."""
        try:
            content = open(DISPATCHER_PATH).read()
            return "255.255.255.255" in content, "firewall-cmd" in content or "ufw allow" in content
        except (OSError, FileNotFoundError):
            return False, False

    def write_dispatcher(self, route, fw):
        """Write or remove dispatcher script based on settings."""
        if not route and not fw:
            try:
                os.remove(DISPATCHER_PATH)
            except OSError:
                pass
            return
        
        lines = [
            '#!/bin/bash',
            '# Auto-generated by zerotier-gui',
            'IFACE="$1"',
            'ACTION="$2"',
            '# Validate interface name',
            '[[ ! "$IFACE" =~ ^zt[a-z0-9]+$ || "$ACTION" != "up" ]] && exit 0'
        ]
        if route:
            lines.append('ip route replace 255.255.255.255/32 dev "$IFACE" 2>/dev/null || true')
        if fw == "firewalld":
            lines.append('firewall-cmd --zone=trusted --add-interface="$IFACE" 2>/dev/null || true')
        elif fw == "ufw":
            lines.append('ufw allow in on zt+ 2>/dev/null || true')
            lines.append('ufw allow out on zt+ 2>/dev/null || true')

        try:
            with open(DISPATCHER_PATH, 'w') as f:
                f.write('\n'.join(lines) + '\n')
            os.chmod(DISPATCHER_PATH, 0o755)
        except OSError:
            pass

    # --- UI sensitivity control ---
    def set_busy(self, busy, status_text=None):
        """Set busy state and grey out all interactive controls."""
        self.busy = busy
        sensitive = not busy
        
        # Spinner
        self.spinner.set_visible(busy)
        if busy:
            self.spinner.start()
            if status_text:
                self.set_status("WARN", status_text)
        else:
            self.spinner.stop()
        
        # Service controls (only if capabilities known)
        if self.has_systemd is not None:
            for btn in self.service_btns:
                btn.set_sensitive(sensitive and self.has_systemd)
            self.enable_check.set_sensitive(sensitive and self.has_systemd)
        
        # Join controls - always disable when busy
        self.join_btn.set_sensitive(sensitive)
        self.join_entry.set_sensitive(sensitive)
        
        # Dispatcher controls (only if capabilities known)
        if self.has_nm is not None:
            self.route_check.set_sensitive(sensitive and self.has_nm)
        if self.fw_type is not None or self.has_systemd is not None:
            self.firewall_check.set_sensitive(sensitive and self.fw_type is not None)

    def _run_async(self, status_text, fn):
        """Run function async if not busy. Returns True if started."""
        if self.busy:
            return False
        self.set_busy(True, status_text)
        self._exec.submit(lambda: (fn(), GLib.idle_add(self.refresh_async)))
        return True

    # --- Toggle handlers (apply immediately + persist) ---
    def on_route_toggled(self, check):
        if self.busy:
            return
        active = check.get_active()
        fw_active = self.firewall_check.get_active()
        
        def work():
            self.write_dispatcher(active, self.fw_type if fw_active else None)
            action = 'add' if active else 'del'
            for iface in self.get_zt_ifaces():
                self.cmd('ip', 'route', action, '255.255.255.255/32', 'dev', iface)
        
        self._run_async('updating route...', work)

    def on_firewall_toggled(self, check):
        if self.busy:
            return
        active = check.get_active()
        route_active = self.route_check.get_active()

        def work():
            self.write_dispatcher(route_active, self.fw_type if active else None)
            
            if self.fw_type == "firewalld":
                for iface in self.get_zt_ifaces():
                    action = '--add-interface' if active else '--remove-interface'
                    self.cmd('firewall-cmd', '--zone=trusted', f'{action}={iface}')
                    
            elif self.fw_type == "ufw":
                if active:
                    self.cmd('ufw', 'allow', 'in', 'on', 'zt+')
                    self.cmd('ufw', 'allow', 'out', 'on', 'zt+')
                else:
                    self.cmd('ufw', 'delete', 'allow', 'in', 'on', 'zt+')
                    self.cmd('ufw', 'delete', 'allow', 'out', 'on', 'zt+')

        self._run_async('updating firewall...', work)

    def on_enable_toggled(self, check):
        if self.busy or not self.has_systemd:
            return
        action = 'enable' if check.get_active() else 'disable'
        self._run_async('updating autostart...', lambda: self.cmd('systemctl', action, 'zerotier-one'))

    # --- Service and network actions ---
    def service_action(self, action):
        if self.busy or not self.has_systemd:
            return
        
        self.set_busy(True, f'{action}ing...')
        expect_active = action in ('start', 'restart')
        
        def work():
            self.cmd('systemctl', action, 'zerotier-one', timeout=15)
            # Poll until service reaches expected state (max 5 seconds)
            for _ in range(10):
                time.sleep(0.5)
                state, _, cli_online = self.get_service_info()
                if expect_active and state == 'active' and cli_online:
                    break
                if state == 'failed':
                    break
                if not expect_active and state in ('inactive', 'failed'):
                    break
            GLib.idle_add(self.refresh_async)
        
        self._exec.submit(work)

    def leave_network(self, nid, name):
        if self.busy:
            return
        
        dlg = Gtk.MessageDialog(
            transient_for=self.win, modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text=f"Leave {name}?"
        )
        
        def on_response(d, response):
            d.destroy()
            if response == Gtk.ResponseType.YES:
                self._run_async('leaving network...', 
                    lambda: (self.cmd('zerotier-cli', 'leave', nid), time.sleep(0.2)))
        
        dlg.connect('response', on_response)
        dlg.present()

    def join_network(self, entry):
        if self.busy:
            return
        nid = entry.get_text().strip()
        
        # Validate 16-char hex network ID
        try:
            valid = len(nid) == 16 and int(nid, 16) >= 0
        except ValueError:
            valid = False
        
        if valid and self._run_async('joining network...', 
                lambda: (self.cmd('zerotier-cli', 'join', nid), time.sleep(0.2))):
            entry.set_text('')

    # --- Async UI refresh ---
    def refresh_async(self):
        """Start async refresh - gathers data in background thread."""
        def worker():
            state, enabled, cli_online = self.get_service_info()
            
            # Parallel fetch of networks and peers
            nets_future = self._exec.submit(
                lambda: self.cmd('zerotier-cli', 'listnetworks') if cli_online else '')
            peers_future = self._exec.submit(
                lambda: self.cmd('zerotier-cli', 'peers') if cli_online else '')
            
            data = {
                'state': state,
                'cli_online': cli_online,
                'enabled': enabled,
                'networks': nets_future.result(),
                'peers': peers_future.result(),
            }
            GLib.idle_add(self._apply_refresh, data)
        
        self._exec.submit(worker)
        return False

    def _apply_refresh(self, data):
        """Apply refresh data to UI (must run on main thread)."""
        self.busy = False
        self.spinner.stop()
        self.spinner.set_visible(False)
        
        state = data['state']
        cli_online = data['cli_online']
        
        # Update status display
        if self.has_systemd is False:
            self.set_status("WARN", "service not found")
        elif state == 'failed':
            self.set_status("OFFLINE", "failed")
        elif state == 'active' and cli_online:
            self.set_status("OK", "active")
        elif state == 'active':
            self.set_status("WARN", "starting...")
        elif cli_online:
            self.set_status("WARN", "active (unmanaged)")
        else:
            self.set_status("OFFLINE", "inactive")
        
        # Update control sensitivity based on capabilities and daemon state
        if self.has_systemd is not None:
            for btn in self.service_btns:
                btn.set_sensitive(self.has_systemd)
            self.enable_check.set_sensitive(self.has_systemd)
        
        self.join_entry.set_sensitive(cli_online)
        self.join_btn.set_sensitive(cli_online)
        
        if self.has_nm is not None:
            self.route_check.set_sensitive(self.has_nm)
        self.firewall_check.set_sensitive(self.fw_type is not None)
        
        # Update enable checkbox without triggering handler
        if self.has_systemd:
            self.enable_check.handler_block(self._enable_hid)
            self.enable_check.set_active(data['enabled'])
            self.enable_check.handler_unblock(self._enable_hid)
        
        # Rebuild network list
        self.clear_box(self.nets)
        if cli_online:
            for line in data['networks'].split('\n')[1:]:
                p = line.split()
                try:
                    if len(p) >= 8 and len(p[2]) == 16 and int(p[2], 16) >= 0:
                        row = Gtk.Box(spacing=10)
                        
                        # Status dot
                        lbl = Gtk.Label(xalign=0)
                        lbl.set_markup(self.dot(p[5]))
                        lbl.set_tooltip_text(p[5])
                        row.append(lbl)
                        
                        # Network name
                        row.append(Gtk.Label(label=p[3], xalign=0, hexpand=True))
                        
                        # IP address
                        ip = p[8] if len(p) > 8 else ''
                        row.append(Gtk.Label(label=ip))
                        
                        # Copy button
                        if ip:
                            cb = Gtk.Button(label="📋")
                            cb.set_tooltip_text("Copy IP")
                            cb.connect('clicked', lambda _, t=ip.split('/')[0]:
                                Gdk.Display.get_default().get_clipboard().set(t))
                            row.append(cb)
                        
                        # Leave button
                        lb = Gtk.Button(label="✕")
                        lb.set_tooltip_text("Leave network")
                        lb.connect('clicked', lambda _, n=p[2], nm=p[3]: self.leave_network(n, nm))
                        row.append(lb)
                        
                        self.nets.append(row)
                except ValueError:
                    pass
        
        if not self.nets.get_first_child():
            self.nets.append(Gtk.Label(label="No networks", xalign=0))
        
        # Rebuild peer list
        self.clear_box(self.peers)
        if cli_online:
            for line in data['peers'].split('\n')[1:]:
                p = line.split()
                if len(p) >= 6 and p[2] == 'LEAF' and p[3] != '-1':
                    row = Gtk.Box(spacing=10)
                    lbl = Gtk.Label(xalign=0)
                    lbl.set_markup(self.dot("OK"))
                    row.append(lbl)
                    row.append(Gtk.Label(label=p[0][:10] + '...', xalign=0, hexpand=True))
                    row.append(Gtk.Label(label=p[3] + 'ms'))
                    self.peers.append(row)
        
        if not self.peers.get_first_child():
            self.peers.append(Gtk.Label(label="No peers connected", xalign=0))
        
        return False

    def _init_capabilities(self):
        """Detect system capabilities in background thread."""
        has_systemd = self.cmd('systemctl', 'cat', 'zerotier-one.service') != ''
        has_nm = self.cmd('systemctl', 'is-active', 'NetworkManager') == 'active'
        fw_type = self.detect_firewall()
        
        def apply():
            self.has_systemd = has_systemd
            self.has_nm = has_nm
            self.fw_type = fw_type
            
            # Disable controls for unavailable features
            if not has_systemd:
                for btn in self.service_btns:
                    btn.set_sensitive(False)
                    btn.set_tooltip_text("No systemd service found")
                self.enable_check.set_sensitive(False)
                self.enable_check.set_tooltip_text("No systemd service found")
            
            if not has_nm:
                self.route_check.set_sensitive(False)
                self.route_check.set_tooltip_text("NetworkManager not active")
            
            if not fw_type:
                self.firewall_check.set_sensitive(False)
                self.firewall_check.set_tooltip_text("No firewall detected")
            
            self.refresh_async()
        
        GLib.idle_add(apply)

    def _periodic_refresh(self):
        """Called periodically to refresh UI if not busy."""
        if not self.busy:
            self.refresh_async()
        return True  # Keep repeating

    # --- Window setup ---
    def on_activate(self, app):
        # Apply theme if passed through
        if theme := os.environ.get('GTK_THEME'):
            Gtk.Settings.get_default().set_property('gtk-theme-name', theme)
        
        self.win = Gtk.ApplicationWindow(application=app, title="ZeroTier")
        self.win.set_resizable(False)
        self.win.set_size_request(340, -1)
        
        # Set up icon search path
        if user_home := os.environ.get('USER_HOME'):
            Gtk.IconTheme.get_for_display(self.win.get_display()).add_search_path(
                f"{user_home}/.local/share/icons")
        self.win.set_icon_name("zerotier-gui")
        
        # Main container
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(15)
        box.set_margin_bottom(15)
        box.set_margin_start(15)
        box.set_margin_end(15)
        
        # Status row with spinner
        status_row = Gtk.Box(spacing=8)
        self.status = Gtk.Label(xalign=0, hexpand=True)
        self.spinner = Gtk.Spinner()
        self.spinner.set_visible(False)
        status_row.append(self.status)
        status_row.append(self.spinner)
        
        # Network and peer containers
        self.nets = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.peers = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        
        for w in [status_row, Gtk.Label(label="Networks", xalign=0), Gtk.Separator(), self.nets]:
            box.append(w)
        
        # Join row
        join_row = Gtk.Box(spacing=5)
        self.join_entry = Gtk.Entry(placeholder_text="Network ID", max_length=16, hexpand=True)
        self.join_entry.connect('activate', self.join_network)
        join_row.append(self.join_entry)
        self.join_btn = Gtk.Button(label="Join")
        self.join_btn.connect('clicked', lambda _: self.join_network(self.join_entry))
        join_row.append(self.join_btn)
        box.append(join_row)
        
        for w in [Gtk.Label(label="Peers", xalign=0), Gtk.Separator(), self.peers]:
            box.append(w)
        
        # Service buttons
        btns = Gtk.Box(spacing=10, homogeneous=True)
        self.service_btns = []
        for label, action in [("Start", "start"), ("Stop", "stop"), ("Restart", "restart")]:
            btn = Gtk.Button(label=label, sensitive=False)
            btn.connect('clicked', lambda _, a=action: self.service_action(a))
            btns.append(btn)
            self.service_btns.append(btn)
        box.append(btns)
        
        # Autostart checkbox
        self.enable_check = Gtk.CheckButton(label="Start on boot", sensitive=False)
        self.enable_check.set_tooltip_text("Enable or disable ZeroTier service at startup")
        self._enable_hid = self.enable_check.connect('toggled', self.on_enable_toggled)
        box.append(self.enable_check)
        box.append(Gtk.Separator())
        
        # Dispatcher options
        route_state, fw_state = self.read_dispatcher()
        
        self.route_check = Gtk.CheckButton(
            label="Broadcast route (LAN discovery)", active=route_state, sensitive=False)
        self.route_check.set_tooltip_text(
            "Adds broadcast route for LAN game discovery. Applies to all ZeroTier networks.")
        self.route_check.connect('toggled', self.on_route_toggled)
        box.append(self.route_check)
        
        self.firewall_check = Gtk.CheckButton(
            label="Trusted firewall zone", active=fw_state, sensitive=False)
        self.firewall_check.set_tooltip_text(
            "Allows all traffic on ZeroTier interfaces. Applies to all ZeroTier networks.")
        self.firewall_check.connect('toggled', self.on_firewall_toggled)
        box.append(self.firewall_check)
        
        self.win.set_child(box)
        self.win.present()
        
        # Show loading state
        self.set_status("WARN", "loading...")
        self.spinner.set_visible(True)
        self.spinner.start()
        
        # Detect capabilities async, then refresh
        self._exec.submit(self._init_capabilities)
        GLib.timeout_add(5000, self._periodic_refresh)


# --- Entry point ---
if __name__ == '__main__':
    if not shutil.which('zerotier-cli'):
        # Show error dialog if ZeroTier not installed
        app = Gtk.Application(application_id='com.local.zerotier-gui.error')
        
        def on_activate(a):
            win = Gtk.ApplicationWindow(application=a, title="Error")
            win.set_default_size(300, 100)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
            box.set_margin_top(20)
            box.set_margin_bottom(20)
            box.set_margin_start(20)
            box.set_margin_end(20)
            box.append(Gtk.Label(label="ZeroTier not found"))
            box.append(Gtk.Label(label="Please install ZeroTier first."))
            btn = Gtk.Button(label="OK")
            btn.connect('clicked', lambda _: a.quit())
            box.append(btn)
            win.set_child(box)
            win.present()
        
        app.connect('activate', on_activate)
        app.run()
        sys.exit(1)
    
    ZerotierGUI().run()
