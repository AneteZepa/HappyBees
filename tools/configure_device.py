import serial
import time
import socket
import argparse
import sys

def get_local_ip():
    """Robustly detect the computer's LAN IP address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't need to be reachable, just tells the OS which interface is active
        s.connect(('8.8.8.8', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def send_command(ser, cmd, delay=0.5):
    """Send a command and print the response."""
    print(f"Sending: {cmd}")
    ser.write(f"{cmd}\n".encode())
    time.sleep(delay)
    
    response = ""
    while ser.in_waiting:
        try:
            line = ser.readline().decode(errors='ignore').strip()
            if line:
                print(f"  >> {line}")
                response += line + "\n"
        except Exception:
            pass
    return response

def main():
    parser = argparse.ArgumentParser(description="BeeWatch Pico Provisioning Tool")
    parser.add_argument("--port", "-p", default="/dev/tty.usbmodem2101", help="Serial port (e.g., /dev/ttyACM0)")
    parser.add_argument("--ssid", "-s", default="TP-Link_D41C", help="WiFi SSID")
    parser.add_argument("--password", "-pw", default="89716632", help="WiFi Password")
    parser.add_argument("--ip", "-i", help="Server IP (Optional, auto-detected if omitted)")
    
    args = parser.parse_args()

    # 1. Determine Server IP
    server_ip = args.ip if args.ip else get_local_ip()
    print(f"\n[CONF] Target Server IP: {server_ip}")
    print(f"[CONF] WiFi Network:     {args.ssid}")
    
    try:
        # 2. Open Serial Connection
        print(f"[INIT] Opening {args.port}...")
        ser = serial.Serial(args.port, 115200, timeout=1)
        time.sleep(2) # Wait for DTR reset
        
        # 3. Clear buffer & Ping
        ser.reset_input_buffer()
        send_command(ser, "\n") # Wake up prompt
        
        # 4. Configure WiFi
        cmd_wifi = f"wifi {args.ssid} {args.password}"
        send_command(ser, cmd_wifi, delay=1.0)
        
        # 5. Configure Server
        cmd_server = f"server {server_ip}"
        send_command(ser, cmd_server, delay=1.0)
        
        print("\n[SUCCESS] Configuration sent. Please reboot the Pico manually.")
        
    except serial.SerialException as e:
        print(f"\n[ERROR] Could not connect to {args.port}")
        print(f"Details: {e}")
        print("Check if 'tio' or another terminal is currently holding the port open.")
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
    finally:
        if 'ser' in locals() and ser.is_open:
            ser.close()

if __name__ == "__main__":
    main()
