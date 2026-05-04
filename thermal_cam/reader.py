# SPDX-License-Identifier: GPL-3.0-or-later
"""
reader.py -- Background thread that reads MLX90640 frames from serial port.
Frame format (GY-MCU90640 AT32F415 bridge, UART mode):
  5A 5A XX XX [768 x little-endian int16]  = 1540 bytes total
  Temperature = raw / 100.0  (degrees C)
"""

import threading
import serial
import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal


FRAME_HEADER  = b'\x5A\x5A'
PIXELS        = 768
FRAME_BODY    = 2 + PIXELS * 2   # 2 type bytes + pixel data


class FrameReader(QObject):
    """
    Runs in a QThread-compatible background thread.
    Emits frame_ready(np.ndarray shape=(24,32) float32) on each complete frame.
    Emits error(str) on serial/parse errors.
    Emits connected(str) / disconnected() for status.
    """

    frame_ready  = pyqtSignal(object)   # np.ndarray (24, 32)
    error        = pyqtSignal(str)
    connected    = pyqtSignal(str)
    disconnected = pyqtSignal()

    def __init__(self, port: str = "/dev/ttyUSB0", baud: int = 115200):
        super().__init__()
        self.port  = port
        self.baud  = baud
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---------------------------------------------------------------- control

    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)

    # ---------------------------------------------------------------- private

    def _run(self):
        ser = None
        try:
            ser = serial.Serial(self.port, self.baud, timeout=2)
            ser.reset_input_buffer()
            self.connected.emit("{} @ {} baud".format(self.port, self.baud))
        except Exception as e:
            self.error.emit("Cannot open {}: {}".format(self.port, e))
            return

        buf = bytearray(FRAME_BODY)

        try:
            while not self._stop.is_set():
                # --- sync to 5A 5A header ---
                state = 0
                while state < 2 and not self._stop.is_set():
                    b = ser.read(1)
                    if not b:
                        continue
                    state = state + 1 if b[0] == 0x5A else 0

                if self._stop.is_set():
                    break

                # --- read frame body ---
                received = 0
                while received < FRAME_BODY and not self._stop.is_set():
                    chunk = ser.read(FRAME_BODY - received)
                    if chunk:
                        n = len(chunk)
                        buf[received:received + n] = chunk
                        received += n

                if received < FRAME_BODY:
                    continue

                # --- parse pixels (skip 2 type bytes) ---
                raw = np.frombuffer(buf, dtype='<i2', count=PIXELS, offset=2)
                frame = raw.astype(np.float32) / 100.0
                print("Frame OK min={:.1f} max={:.1f}".format(frame.min(), frame.max()))
                self.frame_ready.emit(frame.reshape(24, 32))

        except Exception as e:
            if not self._stop.is_set():
                self.error.emit("Serial error: {}".format(e))
        finally:
            try:
                ser.close()
            except Exception:
                pass
            self.disconnected.emit()
