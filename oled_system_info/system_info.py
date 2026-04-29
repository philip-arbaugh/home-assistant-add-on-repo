#!/usr/bin/env python3
"""
OLED System Info Display
Displays system information on SSD1306 OLED with GPIO button control
Uses gpiod and smbus2 for container compatibility
"""

import time
import subprocess
import os
import sys
import gpiod
from smbus2 import SMBus, i2c_msg
from PIL import Image, ImageDraw, ImageFont
import adafruit_ssd1306
import psutil
import requests


def log(message):
    """Print log message with timestamp"""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] {message}", flush=True)


def supervisor_api(endpoint):
    """Call Home Assistant Supervisor API"""
    try:
        response = requests.get(
            f'http://supervisor/{endpoint}',
            headers={'Authorization': f'Bearer {os.getenv("SUPERVISOR_TOKEN")}'},
            timeout=5
        )
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        log(f"API Error ({endpoint}): {e}")
    return None


class I2CAdapter:
    """SMBus adapter for Adafruit CircuitPython libraries"""
    
    def __init__(self, bus_number=1):
        self.bus = SMBus(bus_number)
        self._locked = False
    
    def try_lock(self):
        if not self._locked:
            self._locked = True
            return True
        return False
    
    def unlock(self):
        self._locked = False
    
    def writeto(self, address, buffer, *, start=0, end=None):
        if end is None:
            end = len(buffer)
        
        length = end - start
        if length == 0:
            try:
                self.bus.read_byte(address)
            except:
                pass
            return
        
        data = bytes(buffer[start:end])
        msg = i2c_msg.write(address, data)
        self.bus.i2c_rdwr(msg)
    
    def readfrom_into(self, address, buffer, *, start=0, end=None):
        if end is None:
            end = len(buffer)
        
        length = end - start
        msg = i2c_msg.read(address, length)
        self.bus.i2c_rdwr(msg)
        
        for i, byte in enumerate(msg):
            buffer[start + i] = byte


def get_system_info():
    """Retrieve HOST system information via Supervisor API"""
    # Get host info
    host_info = supervisor_api('host/info')
    network_info = supervisor_api('network/info')
    os_info = supervisor_api('os/info')
    
    # Hostname
    if host_info and 'data' in host_info:
        hostname = host_info['data'].get('hostname', 'unknown')
    else:
        hostname = subprocess.check_output("hostname", shell=True).decode('UTF-8').strip()
    
    # IP address - try to get primary network interface
    ip = "0.0.0.0"
    if network_info and 'data' in network_info:
        interfaces = network_info['data'].get('interfaces', [])
        for iface in interfaces:
            if iface.get('primary', False) and iface.get('ipv4'):
                ip = iface['ipv4'].get('address', ['0.0.0.0'])[0].split('/')[0]
                break
        # Fallback to first interface with an IP
        if ip == "0.0.0.0":
            for iface in interfaces:
                if iface.get('ipv4') and iface['ipv4'].get('address'):
                    ip = iface['ipv4']['address'][0].split('/')[0]
                    if not ip.startswith('172.'):  # Skip docker networks
                        break
    
    if ip == "0.0.0.0":
        try:
            ip = subprocess.check_output("hostname -I | cut -d' ' -f1", shell=True).decode('UTF-8').strip()
        except:
            pass
    
    # CPU and Memory - use host /proc if mounted, otherwise container stats
    try:
        # Try to read from host /proc
        if os.path.exists('/host/proc/stat'):
            # We'd need to parse /proc/stat manually - complex
            # For now, fall back to psutil on container
            cpu = f"{psutil.cpu_percent():3.0f}"
        else:
            cpu = f"{psutil.cpu_percent():3.0f}"
    except:
        cpu = "N/A"
    
    try:
        # Try to read from host /proc/meminfo
        if os.path.exists('/host/proc/meminfo'):
            with open('/host/proc/meminfo', 'r') as f:
                meminfo = {}
                for line in f:
                    parts = line.split(':')
                    if len(parts) == 2:
                        meminfo[parts[0].strip()] = int(parts[1].strip().split()[0])
                
                total = meminfo.get('MemTotal', 0)
                available = meminfo.get('MemAvailable', 0)
                if total > 0:
                    used_percent = ((total - available) / total) * 100
                    mem = f"{used_percent:2.0f}"
                else:
                    mem = f"{psutil.virtual_memory().percent:2.0f}"
        else:
            mem = f"{psutil.virtual_memory().percent:2.0f}"
    except:
        mem = "N/A"
    
    return hostname, ip, cpu, mem


def main():
    log("Initializing OLED System Info Display")
    
    # GPIO configuration (LED only, no button)
    LED = 23
    
    log(f"Configuring GPIO - LED: GPIO{LED}")
    chip = gpiod.Chip('gpiochip0')
    led_line = chip.get_line(LED)
    led_line.request(consumer="oled-display", type=gpiod.LINE_REQ_DIR_OUT, default_vals=[0])
    log("GPIO configured successfully")
    
    # Display configuration
    log("Initializing I2C and OLED display")
    i2c = I2CAdapter(1)
    disp = adafruit_ssd1306.SSD1306_I2C(128, 32, i2c)
    disp.rotation = 2
    disp.fill(0)
    disp.show()
    log("OLED display initialized")
    
    # Drawing setup
    image = Image.new("1", (disp.width, disp.height))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    
    padding = -2
    x = 0
    top = padding
    
    # Turn on LED
    led_line.set_value(1)
    log("Status LED turned on")
    
    # Startup message
    log("Displaying startup message")
    draw.rectangle((0, 0, disp.width, disp.height), outline=0, fill=0)
    draw.text((x, top),    "--------------------", font=font, fill=255)
    draw.text((x, top+12), " Infoscreen Started ", font=font, fill=255)
    draw.text((x, top+24), "--------------------", font=font, fill=255)
    disp.image(image)
    disp.show()
    time.sleep(5)
    
    log("Entering main loop")
    
    try:
        while True:
            draw.rectangle((0, 0, disp.width, disp.height), outline=0, fill=0)
            
            hostname, ip, cpu, mem = get_system_info()
            draw.text((x, top),    f"NAME: {hostname}", font=font, fill=255)
            draw.text((x, top+12), f"IP  : {ip}", font=font, fill=255)
            draw.text((x, top+24), f"CPU : {cpu}% | MEM: {mem}%", font=font, fill=255)
            
            disp.image(image)
            disp.show()
            
            time.sleep(2)
    
    except KeyboardInterrupt:
        log("Received keyboard interrupt")
    except Exception as e:
        log(f"ERROR: {e}")
        raise
    finally:
        log("Cleaning up GPIO resources")
        led_line.release()
        log("Shutdown complete")

if __name__ == "__main__":
    main()
