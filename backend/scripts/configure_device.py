#!/usr/bin/env python3
"""
HappyBees Device Configuration Tool

Provisions WiFi credentials and server settings to a Pico device via serial.

Usage:
    python backend/scripts/configure_device.py -d /dev/tty.usbmodem2101 \\
        --ssid "MyNetwork" --password "MyPassword" --server 192.168.0.100
"""

import argparse
import time
import serial
import serial.tools.list_ports


def list_ports():
    """List available serial ports."""
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("No serial ports found.")
        return
    print("Available serial ports:")
    for port in ports:
        print(f"  {port.device} - {port.description}")


def configure_device(device, ssid=None, password=None, server=None, node_id=None):
    """Send configuration commands to the device."""
    print(f"Connecting to {device}...")

    try:
        ser = serial.Serial(device, 115200, timeout=2)
    except serial.SerialException as e:
        print(f"ERROR: Could not open {device}: {e}")
        return False

    time.sleep(1)
    ser.reset_input_buffer()

    def send_command(cmd):
        """Send a command and print response."""
        print(f"> {cmd}")
        ser.write(f"{cmd}\n".encode())
        time.sleep(0.5)
        while ser.in_waiting:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line:
                print(f"  {line}")

    # Send configuration commands
    if ssid and password:
        send_command(f"wifi {ssid} {password}")
        time.sleep(0.5)

    if server:
        send_command(f"server {server}")
        time.sleep(0.5)

    if node_id:
        send_command(f"node {node_id}")
        time.sleep(0.5)

    # Ping to verify
    send_command("p")

    ser.close()
    print("\nConfiguration complete.")
    return True


def main():
    parser = argparse.ArgumentParser(description="HappyBees Device Configuration")
    parser.add_argument('-d', '--device', help='Serial device path')
    parser.add_argument('--ssid', help='WiFi SSID')
    parser.add_argument('--password', help='WiFi password')
    parser.add_argument('--server', help='Server IP address')
    parser.add_argument('--node-id', help='Node ID')
    parser.add_argument('--list', action='store_true', help='List available ports')

    args = parser.parse_args()

    if args.list:
        list_ports()
        return

    if not args.device:
        print("ERROR: No device specified. Use -d /dev/tty.usbmodem* or --list")
        return

    configure_device(
        args.device,
        ssid=args.ssid,
        password=args.password,
        server=args.server,
        node_id=args.node_id
    )


if __name__ == "__main__":
    main()
