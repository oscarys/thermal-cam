# thermal-cam

MLX90640 32x24 IR thermal camera viewer for the GY-MCU90640 breakout board,
using an ESP32 as a transparent UART bridge and a PyQt6 desktop application
for live display, colormap rendering, frame saving, and sequence recording.

**UAM Iztapalapa -- LINI | M.Sc. Oscar Yanez Suarez | GPL-3.0**

---

## Hardware

| Component | Details |
|-----------|---------|
| Sensor | Melexis MLX90640 32x24 IR thermal camera |
| Breakout | GY-MCU90640 (AT32F415 bridge MCU) |
| Microcontroller | ESP32 (MicroPython, UART bridge only) |
| Host | Any Linux/macOS/Windows PC with Python 3.11+ |

### Wiring

```
GY-MCU90640          ESP32
-----------          -----
TX  ------------>  GPIO 17  (UART2 RX)
RX  <------------  GPIO 16  (UART2 TX)
PS  ------------>  3.3V     (UART mode select -- see note below)
VCC ------------>  3.3V
GND ------------>  GND
                   USB ----> PC /dev/ttyUSB0
```

> **PS pin** selects the external interface of the AT32F415 bridge:
> - PS = GND  -> I2C mode  (address 0x33)
> - PS = HIGH -> UART mode (115200 baud, binary frame stream)
>
> This pin must be set **before power-up**. If left floating the board
> behaviour is undefined and may lock up.

---

## Project structure

```
thermal-cam/
|-- main.py                     # PyQt6 app entry point
|-- requirements.txt
|-- README.md
|-- docs/
|   +-- MLX90640-Datasheet_Melexis.pdf
|-- esp32/
|   +-- main.py                 # MicroPython UART bridge (upload to ESP32)
+-- thermal_cam/
    |-- __init__.py
    |-- app.py                  # MainWindow, controls, rendering
    |-- reader.py               # Background UART reader thread
    |-- colormaps.py            # Inferno / Turbo / Ironbow / Grayscale LUTs
    +-- recorder.py             # Single-frame and sequence saving
```

---

## Installation

```bash
pip install -r requirements.txt
```

### ESP32 setup

Flash MicroPython (>=1.20) to the ESP32, then upload the bridge firmware:

```bash
mpremote connect /dev/ttyUSB0 cp esp32/main.py :main.py
mpremote connect /dev/ttyUSB0 reset
```

The bridge is a minimal pass-through -- it reads the GY-MCU90640 UART stream
and writes it verbatim to USB serial. No Wi-Fi, no web server, no asyncio.

### Running the app

```bash
python main.py
```

Default port: `/dev/ttyUSB0` at 115200 baud.
Change via **Connection -> Settings**.

---

## Features

| Feature | Details |
|---------|---------|
| Live view | 32x24 pixels, ~2 Hz update rate |
| Interpolation | Bilinear (smooth) or nearest-neighbour |
| Colormaps | Inferno, Turbo, Ironbow, Grayscale |
| Gain | 0.5x -- 3.0x contrast slider |
| Crosshair | Hover to read pixel temperature in degC |
| Statistics | Min / max / average temperature + FPS |
| Save frame | PNG (false-colour, matches display), CSV (raw degC), NPZ (numpy) |
| Record sequence | NPZ archive, shape (N, 24, 32), float32 degC |

### Loading a saved sequence

```python
import numpy as np
data = np.load("seq_20240501_120000.npz")
seq  = data["sequence"]   # shape (N, 24, 32), float32, degrees C
```

---

## Development notes: the long road from I2C to UART

This section documents the non-obvious hardware behaviour of the GY-MCU90640
board that makes a naive I2C approach fail, and explains why UART is the
correct interface for this particular product.

### What we expected

The MLX90640 datasheet describes a standard I2C interface at address 0x33.
The natural first approach was to write a MicroPython I2C driver that reads
the 832-word EEPROM for calibration parameters, then reads the 832-word RAM
on each frame acquisition, runs the Melexis compensation math, and serves
the resulting temperature array over a web interface.

### What we found: the AT32F415 bridge

The GY-MCU90640 breakout does **not** expose the MLX90640 I2C bus directly.
Instead, an Artery Technology AT32F415 ARM Cortex-M4 microcontroller sits
between the sensor and the external headers. This bridge MCU:

- Reads the MLX90640 internally at its native I2C interface
- Exposes a **simplified** external interface selected by the PS pin
- In I2C mode (PS=GND): presents address 0x33, passes EEPROM reads through,
  but intercepts all register writes
- In UART mode (PS=HIGH): streams complete processed frames at 115200 baud

The presence of the bridge was not obvious from the board silkscreen or the
product listing, which simply describes it as an "MLX90640 breakout". The
AT32F415 chip is small and located near the I2C/UART header.

### I2C failure modes encountered

Several issues appeared before the bridge was identified:

**1. PS pin floating**

The first symptom was [Errno 19] ENODEV -- the sensor not appearing on the
I2C bus at all. The PS pin was floating, causing the bridge to select an
indeterminate interface. Grounding PS fixed the scan (i2c.scan() returned
[51] = 0x33).

**2. I2C timeout on EEPROM read**

With a naive single-transaction read of 832 words (1664 bytes), MicroPython
raised [Errno 116] ETIMEDOUT. The fix required chunked reads using
readfrom_mem(..., addrsize=16) with 16-word chunks at 100 kHz.

**3. Register writes silently ignored**

The control register (0x800D) and status register (0x8000) writes using the
standard 4-byte I2C write (writeto with register address + value) were
accepted by the bus but had no effect. The AT32F415 bridge acknowledged the
write electrically but discarded it internally.

The correct write method turned out to be writeto_mem(..., addrsize=16),
which the bridge does honour for the status register clear -- but not for
the control register. Refresh rate and subpage mode cannot be changed from
the outside.

**4. Only subpage 0 ever delivered**

The MLX90640 updates a 32x24 frame in two passes (subpage 0: even pixels,
subpage 1: odd pixels). A complete frame requires both subpages. Through I2C,
the bridge only ever reported subpage 0 in the status register, regardless of
how long the host waited. Subpage 1 was never signalled.

This means the I2C interface exposed by the AT32F415 is a degraded view:
read-only calibration data and single-subpage frame data, with no ability to
configure the sensor or reliably acquire complete frames.

**5. Memory fragmentation on ESP32**

The I2C driver allocated large Python lists for EEPROM (832 integers) and RAM
(832 integers) on every frame. MicroPython's heap fragmented quickly, leading
to "memory allocation failed, allocating 4096 bytes" errors. Switching to
array('H') typed arrays reduced per-element overhead from ~16 bytes to 2
bytes, but the fundamental I2C reliability problems remained.

**6. MicroPython asyncio and blocking I2C**

The web server approach required serving HTTP and SSE concurrently with
the I2C frame acquisition loop. MicroPython's cooperative asyncio scheduler
cannot preempt a blocking readfrom_mem() call. A full RAM read (832 words,
16-word chunks, 2 ms inter-chunk delay) took 350 ms at 100 kHz, starving
the web server coroutines entirely. Removing the delays reduced this to
~96 ms at 400 kHz, but still caused visible stuttering and dropped
connections on every frame.

### Why UART works correctly

In UART mode (PS=HIGH) the AT32F415 acquires both subpages internally,
applies the Melexis calibration compensation itself, and streams complete
32x24 temperature frames at ~2 Hz. Each frame is:

```
5A 5A  XX XX  [768 x little-endian int16]
header  type   pixel data (1536 bytes)
```

Total: 1540 bytes per frame at 115200 baud = ~107 ms transfer time.

Temperature in degC = raw_int16 / 100.0

This was confirmed by inspecting the raw stream: pixels in a room-temperature
scene decoded to 25-26 degC, consistent with the environment.

The UART interface bypasses all the I2C register write restrictions, subpage
management issues, and MicroPython memory fragmentation problems in one move.
The ESP32 becomes a trivial 10-line USB-UART bridge, and all frame processing
moves to the PC where Python has no memory constraints.

### Lessons

- Verify the board schematic before writing drivers. Many "sensor breakout"
  boards include bridge MCUs that present a modified interface.
- Check all pins. The PS pin is not documented on most GY-MCU90640 product
  pages but is critical for interface selection.
- Test register writes explicitly. An I2C write that is electrically ACKed
  is not necessarily processed by the target device.
- MicroPython asyncio and blocking I2C do not mix well. The cooperative
  scheduler cannot preempt a blocking readfrom_mem() call, starving all
  other coroutines including the web server.

---

## Frame format reference

```
Offset  Size    Content
------  ----    -------
0       2       Header: 0x5A 0x5A
2       2       Frame type / sequence (ignore)
4       1536    768 x little-endian signed 16-bit integers
                Temperature (degC) = value / 100.0
                Pixel order: row-major, top-left to bottom-right
                Row 0..23, Column 0..31
```

---

## License

GPL-3.0 -- see LICENSE

(c) M.Sc. Oscar Yanez Suarez -- UAM Iztapalapa, LINI
