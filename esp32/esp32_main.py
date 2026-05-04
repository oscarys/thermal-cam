# SPDX-License-Identifier: GPL-3.0-or-later
# ESP32 MicroPython -- transparent UART bridge
# GY-MCU90640 (UART2) -> USB serial (stdout)
# PS pin on GY-MCU90640 must be HIGH (3.3V) for UART mode
#
# Wiring:
#   GY-MCU90640 TX -> ESP32 GPIO 17
#   GY-MCU90640 RX -> ESP32 GPIO 16
#   GY-MCU90640 PS -> 3.3V
#   GY-MCU90640 VCC -> 3.3V
#   GY-MCU90640 GND -> GND
#
# UAM Iztapalapa -- LINI | M.Sc. Oscar Yanez Suarez | GPL-3.0

from machine import UART, Pin
import sys

uart = UART(2, baudrate=115200, tx=Pin(16), rx=Pin(17), rxbuf=4096)

while True:
    n = uart.any()
    if n:
        sys.stdout.buffer.write(uart.read(n))
