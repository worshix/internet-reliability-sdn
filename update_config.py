#!/usr/bin/env python3
"""
ZAN config updater
Updates MAC addresses and Jetson IP across all ESP32 firmware files and README.

Usage (interactive — prompts for each value, Enter to keep current):
    python3 update_config.py

Usage (non-interactive — supply any combination of flags):
    python3 update_config.py --jetson-ip 192.168.1.42
    python3 update_config.py --gateway AA:BB:CC:DD:EE:FF --node2 AA:BB:CC:DD:EE:FF
    python3 update_config.py --jetson-ip 192.168.1.42 \
        --gateway AA:BB:CC:DD:EE:FF --node2 AA:BB:CC:DD:EE:FF \
        --node3   AA:BB:CC:DD:EE:FF --node4 AA:BB:CC:DD:EE:FF \
        --node5   AA:BB:CC:DD:EE:FF
"""

import re
import os
import sys
import argparse

# ── paths ────────────────────────────────────────────────────────────────────
ROOT    = os.path.dirname(os.path.abspath(__file__))
ESP_DIR = os.path.join(ROOT, "esp32")

INO_FILES = {
    "gateway": os.path.join(ESP_DIR, "gateway", "gateway.ino"),
    "node2":   os.path.join(ESP_DIR, "node_1",  "node_1.ino"),
    "node3":   os.path.join(ESP_DIR, "node_2",  "node_2.ino"),
    "node4":   os.path.join(ESP_DIR, "node_3",  "node_3.ino"),
    "node5":   os.path.join(ESP_DIR, "node_4",  "node_4.ino"),
}
README = os.path.join(ROOT, "README.md")

# ── helpers ──────────────────────────────────────────────────────────────────
def mac_to_cpp(mac: str) -> str:
    """'AA:BB:CC:DD:EE:FF'  →  '{0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF}'"""
    parts = mac.upper().split(":")
    if len(parts) != 6 or any(len(p) != 2 for p in parts):
        raise ValueError(f"Invalid MAC: {mac!r}  (expected XX:XX:XX:XX:XX:XX)")
    return "{" + ", ".join(f"0x{p}" for p in parts) + "}"

def validate_ip(ip: str) -> str:
    parts = ip.split(".")
    if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        raise ValueError(f"Invalid IP: {ip!r}  (expected x.x.x.x)")
    return ip

def read_file(path: str) -> str:
    with open(path, "r") as f:
        return f.read()

def write_file(path: str, content: str) -> None:
    with open(path, "w") as f:
        f.write(content)

# ── current-value readers ────────────────────────────────────────────────────
def current_mac(content: str, var: str) -> str:
    """Extract current hex bytes for a MAC variable, return as XX:XX:XX:XX:XX:XX."""
    m = re.search(rf"uint8_t\s+{re.escape(var)}\[6\]\s*=\s*\{{([^}}]+)\}}", content)
    if not m:
        return "??"
    parts = [p.strip().replace("0x", "") for p in m.group(1).split(",")]
    return ":".join(parts)

def current_ip(content: str) -> str:
    m = re.search(r'const char\*\s+MQTT_BROKER\s*=\s*"([^"]+)"', content)
    return m.group(1) if m else "??"

# ── appliers ─────────────────────────────────────────────────────────────────
def apply_mac(content: str, var: str, mac: str) -> str:
    cpp = mac_to_cpp(mac)
    pattern = rf"(uint8_t\s+{re.escape(var)}\[6\]\s*=\s*)\{{[^}}]+\}}(;)"
    result, n = re.subn(pattern, rf"\g<1>{cpp}\2", content)
    if n == 0:
        print(f"  WARNING: {var} not found — skipped")
    return result

def apply_ip(content: str, ip: str) -> str:
    result, n = re.subn(
        r'(const char\*\s+MQTT_BROKER\s*=\s*")[^"]+(")',
        rf"\g<1>{ip}\g<2>",
        content,
    )
    if n == 0:
        print("  WARNING: MQTT_BROKER not found — skipped")
    return result

def apply_readme_mac(content: str, board_label: str, mac: str) -> str:
    """Update a row in the README MAC table."""
    pattern = rf"(\|\s*{re.escape(board_label)}[^|]*\|[^|]*\|\s*)`[^`]*`([^|]*\|)"
    result, n = re.subn(pattern, rf"\g<1>`{mac}`\g<2>", content)
    if n == 0:
        print(f"  README: row for '{board_label}' not found — skipped")
    return result

def apply_readme_ip(content: str, ip: str) -> str:
    # matches:  **Jetson IP (fill in when known):** `___.___.___.___ `
    # or after update: **Jetson IP (fill in when known):** `192.168.1.42`
    result, n = re.subn(
        r"(\*\*Jetson IP[^*]*\*\*[^`]*`)[^`]*(`)",
        rf"\g<1>{ip}\g<2>",
        content,
    )
    if n == 0:
        print("  README: Jetson IP line not found — skipped")
    return result

# ── interactive prompt ────────────────────────────────────────────────────────
def prompt(label: str, current: str, validator=None) -> str | None:
    """Show current value, return new value or None to keep."""
    raw = input(f"  {label} [{current}]: ").strip()
    if raw == "":
        return None
    if validator:
        raw = validator(raw)
    return raw

# ── main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="ZAN firmware config updater")
    parser.add_argument("--jetson-ip", metavar="IP")
    parser.add_argument("--gateway",   metavar="MAC")
    parser.add_argument("--node2",     metavar="MAC")
    parser.add_argument("--node3",     metavar="MAC")
    parser.add_argument("--node4",     metavar="MAC")
    parser.add_argument("--node5",     metavar="MAC")
    args = parser.parse_args()

    interactive = not any(vars(args).values())

    # load all file contents
    contents = {k: read_file(p) for k, p in INO_FILES.items()}
    readme   = read_file(README)

    # gather current values
    # GATEWAY_MAC only lives in sensor node files; all other MACs live in gateway
    gw  = contents["gateway"]
    n2  = contents["node2"]
    cur = {
        "jetson_ip": current_ip(gw),
        "gateway":   current_mac(n2,  "GATEWAY_MAC"),   # node files know gw MAC
        "node2":     current_mac(gw,  "NODE2_MAC"),
        "node3":     current_mac(gw,  "NODE3_MAC"),
        "node4":     current_mac(gw,  "NODE4_MAC"),
        "node5":     current_mac(gw,  "NODE5_MAC"),
    }

    print("\n── ZAN Config Updater ───────────────────────────────")
    if interactive:
        print("Press Enter to keep the current value.\n")
        try:
            new_ip  = prompt("Jetson IP        ", cur["jetson_ip"], validate_ip)
            new_gw  = prompt("Gateway MAC (#1) ", cur["gateway"])
            new_n2  = prompt("Node2 MAC   (#2) ", cur["node2"])
            new_n3  = prompt("Node3 MAC   (#3) ", cur["node3"])
            new_n4  = prompt("Node4 MAC   (#4) ", cur["node4"])
            new_n5  = prompt("Node5 MAC   (#5) ", cur["node5"])
        except KeyboardInterrupt:
            print("\nCancelled.")
            sys.exit(0)
    else:
        new_ip = validate_ip(args.jetson_ip) if args.jetson_ip else None
        new_gw = args.gateway
        new_n2 = args.node2
        new_n3 = args.node3
        new_n4 = args.node4
        new_n5 = args.node5

    # validate MACs if supplied via flags (interactive already validated via prompt)
    mac_args = {"gateway": new_gw, "node2": new_n2, "node3": new_n3,
                "node4": new_n4, "node5": new_n5}
    if not interactive:
        for key, val in mac_args.items():
            if val:
                mac_to_cpp(val)   # raises ValueError on bad format

    changes = {
        "jetson_ip": new_ip,
        "gateway":   new_gw,
        "node2":     new_n2,
        "node3":     new_n3,
        "node4":     new_n4,
        "node5":     new_n5,
    }

    if not any(changes.values()):
        print("\nNothing to update.")
        return

    print("\nApplying changes...")

    # MAC variable name in each .ino file
    mac_vars = {
        "gateway": "GATEWAY_MAC",
        "node2":   "NODE2_MAC",
        "node3":   "NODE3_MAC",
        "node4":   "NODE4_MAC",
        "node5":   "NODE5_MAC",
    }

    # README board labels (must match text in README)
    readme_labels = {
        "gateway": "ESP32 #1 (gateway)",
        "node2":   "ESP32 #2",
        "node3":   "ESP32 #3",
        "node4":   "ESP32 #4",
        "node5":   "ESP32 #5",
    }

    # update every .ino file
    for file_key, file_path in INO_FILES.items():
        text = contents[file_key]
        changed = False

        for mac_key, mac_val in mac_args.items():
            if not mac_val:
                continue
            # gateway.ino has no GATEWAY_MAC variable (it IS the gateway)
            if file_key == "gateway" and mac_key == "gateway":
                continue
            new_text = apply_mac(text, mac_vars[mac_key], mac_val)
            if new_text != text:
                changed = True
            text = new_text

        if file_key == "gateway" and new_ip:
            new_text = apply_ip(text, new_ip)
            if new_text != text:
                changed = True
            text = new_text

        if changed:
            write_file(file_path, text)
            print(f"  updated: {os.path.relpath(file_path, ROOT)}")
        else:
            print(f"  no change: {os.path.relpath(file_path, ROOT)}")

    # update README
    readme_changed = False
    for mac_key, mac_val in mac_args.items():
        if mac_val:
            new_readme = apply_readme_mac(readme, readme_labels[mac_key], mac_val)
            if new_readme != readme:
                readme_changed = True
            readme = new_readme

    if new_ip:
        new_readme = apply_readme_ip(readme, new_ip)
        if new_readme != readme:
            readme_changed = True
        readme = new_readme

    if readme_changed:
        write_file(README, readme)
        print(f"  updated: README.md")

    print("\nDone. Summary of applied values:")
    for key, val in changes.items():
        if val:
            label = key.replace("_", " ").replace("jetson ip", "Jetson IP").title()
            print(f"  {label:<18} → {val}")

if __name__ == "__main__":
    main()
