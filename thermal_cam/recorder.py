# SPDX-License-Identifier: GPL-3.0-or-later
"""recorder.py -- Save single frames and record sequences."""

import datetime
import pathlib
import numpy as np


def _timestamp():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def save_frame_csv(frame: np.ndarray, directory: str) -> str:
    """Save raw temperature array as CSV. Returns file path."""
    path = pathlib.Path(directory) / "frame_{}.csv".format(_timestamp())
    np.savetxt(str(path), frame, fmt="%.2f", delimiter=",")
    return str(path)


def save_frame_png(frame: np.ndarray, lut: np.ndarray,
                   gain: float, directory: str) -> str:
    """Save false-colour PNG. Returns file path."""
    mn, mx = frame.min(), frame.max()
    rng = mx - mn if mx != mn else 1.0
    idx = np.clip(((frame - mn) / rng * 255 * gain), 0, 255).astype(np.uint8)
    rgb = lut[idx]                              # (24, 32, 3) uint8

    # Upscale 8x with nearest neighbour (np.kron)
    big = np.kron(rgb, np.ones((8, 8, 1), dtype=np.uint8))  # (192, 256, 3)
    big = np.ascontiguousarray(big)

    path = pathlib.Path(directory) / "frame_{}.png".format(_timestamp())

    from PyQt6.QtGui import QImage
    h, w, _ = big.shape
    stride = w * 3
    img = QImage(big.data, w, h, stride, QImage.Format.Format_RGB888)
    img = img.copy()   # detach from numpy buffer before saving
    img.save(str(path))
    return str(path)


def save_frame_npz(frame: np.ndarray, directory: str) -> str:
    """Save raw frame as compressed numpy archive."""
    path = pathlib.Path(directory) / "frame_{}.npz".format(_timestamp())
    np.savez_compressed(str(path), frame=frame)
    return str(path)


class SequenceRecorder:
    """Accumulates frames into memory then saves as .npz on stop."""

    def __init__(self):
        self._frames: list = []
        self._recording = False
        self._start_time: str = ""

    @property
    def recording(self):
        return self._recording

    @property
    def frame_count(self):
        return len(self._frames)

    def start(self):
        self._frames.clear()
        self._recording = True
        self._start_time = _timestamp()

    def add_frame(self, frame: np.ndarray):
        if self._recording:
            self._frames.append(frame.copy())

    def stop(self, directory: str) -> str:
        """Stop recording and save. Returns file path."""
        self._recording = False
        if not self._frames:
            return ""
        stack = np.stack(self._frames, axis=0)   # (N, 24, 32)
        path  = pathlib.Path(directory) / "seq_{}.npz".format(self._start_time)
        np.savez_compressed(str(path), sequence=stack)
        self._frames.clear()
        return str(path)

    def discard(self):
        self._recording = False
        self._frames.clear()
