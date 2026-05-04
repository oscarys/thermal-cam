# SPDX-License-Identifier: GPL-3.0-or-later
"""app.py -- MainWindow for MLX90640 thermal camera viewer."""

import pathlib
import numpy as np
import pyqtgraph as pg

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QSlider, QPushButton, QStatusBar,
    QGroupBox, QFileDialog, QDialog, QFormLayout,
    QLineEdit, QDialogButtonBox, QSizePolicy, QFrame,
)
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSlot
from PyQt6.QtGui import QAction, QFont, QColor

from .reader    import FrameReader
from .colormaps import COLORMAPS
from .recorder  import SequenceRecorder, save_frame_csv, save_frame_png, save_frame_npz

# -- pyqtgraph global config ---------------------------------------------------
pg.setConfigOption("background", "#0d0d14")
pg.setConfigOption("foreground", "#c8c8d8")
pg.setConfigOptions(antialias=False)

# -- colour palette (matches filter-toolbox dark theme) -----------------------
_PAL = {
    "bg":        "#0d0d14",
    "surface":   "#13131e",
    "border":    "#1e1e30",
    "accent":    "#00d4aa",
    "accent2":   "#ff6b35",
    "text":      "#c8c8d8",
    "muted":     "#5a5a72",
    "rec":       "#e03030",
}

_STYLESHEET = """
QMainWindow, QWidget {{
    background: {bg};
    color: {text};
    font-family: "JetBrains Mono", "Fira Mono", "Consolas", monospace;
    font-size: 11px;
}}
QGroupBox {{
    border: 1px solid {border};
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 4px;
    color: {muted};
    font-size: 10px;
    letter-spacing: 1px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    text-transform: uppercase;
}}
QLabel {{ color: {text}; }}
QComboBox, QLineEdit {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 3px;
    color: {text};
    padding: 3px 6px;
    min-width: 80px;
}}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background: {surface};
    border: 1px solid {border};
    color: {text};
    selection-background-color: {accent};
    selection-color: {bg};
}}
QSlider::groove:horizontal {{
    background: {border};
    height: 4px;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {accent};
    width: 12px; height: 12px;
    margin: -4px 0;
    border-radius: 6px;
}}
QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
QPushButton {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 3px;
    color: {text};
    padding: 4px 12px;
    min-width: 70px;
}}
QPushButton:hover  {{ border-color: {accent}; color: {accent}; }}
QPushButton:pressed {{ background: {border}; }}
QPushButton#rec_btn[recording="true"] {{
    border-color: {rec};
    color: {rec};
}}
QStatusBar {{ background: {surface}; color: {muted}; border-top: 1px solid {border}; }}
QMenuBar {{
    background: {surface};
    color: {text};
    border-bottom: 1px solid {border};
}}
QMenuBar::item:selected {{ background: {border}; }}
QMenu {{
    background: {surface};
    border: 1px solid {border};
    color: {text};
}}
QMenu::item:selected {{ background: {accent}; color: {bg}; }}
""".format(**_PAL)


class SettingsDialog(QDialog):
    def __init__(self, port, baud, save_dir, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(340)

        layout = QFormLayout(self)
        layout.setSpacing(10)

        self.port_edit = QLineEdit(port)
        self.baud_edit = QLineEdit(str(baud))
        self.dir_edit  = QLineEdit(save_dir)

        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.dir_edit)
        dir_row.addWidget(browse)

        layout.addRow("Serial port:", self.port_edit)
        layout.addRow("Baud rate:",   self.baud_edit)
        layout.addRow("Save folder:", dir_row)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Select save folder",
                                             self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)

    def values(self):
        return (self.port_edit.text().strip(),
                int(self.baud_edit.text().strip()),
                self.dir_edit.text().strip())


class ColorbarWidget(QWidget):
    """Horizontal gradient colorbar with min/max labels."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(28)
        self._lut  = COLORMAPS["Inferno"]
        self._mn   = 0.0
        self._mx   = 0.0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._min_lbl = QLabel("--")
        self._bar     = pg.GraphicsLayoutWidget()
        self._bar.setFixedHeight(16)
        self._bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._img     = pg.ImageItem()
        vb = self._bar.addViewBox()
        vb.setMouseEnabled(False, False)
        vb.addItem(self._img)
        self._max_lbl = QLabel("--")

        for lbl in (self._min_lbl, self._max_lbl):
            lbl.setFixedWidth(52)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet("color: {}; font-size: 10px;".format(_PAL["muted"]))

        layout.addWidget(self._min_lbl)
        layout.addWidget(self._bar)
        layout.addWidget(self._max_lbl)
        self._draw_bar()

    def update_range(self, mn, mx):
        self._mn = mn
        self._mx = mx
        self._min_lbl.setText("{:.1f} C".format(mn))
        self._max_lbl.setText("{:.1f} C".format(mx))

    def set_lut(self, lut):
        self._lut = lut
        self._draw_bar()

    def _draw_bar(self):
        bar = np.arange(256, dtype=np.uint8).reshape(1, 256)
        rgba = np.zeros((1, 256, 4), dtype=np.uint8)
        rgba[0, :, :3] = self._lut[bar[0]]
        rgba[0, :,  3] = 255
        self._img.setImage(rgba.transpose(1, 0, 2))


class MainWindow(QMainWindow):
    DEFAULT_PORT    = "/dev/ttyUSB0"
    DEFAULT_BAUD    = 115200
    DEFAULT_SAVEDIR = str(pathlib.Path.home() / "thermal_captures")

    def __init__(self):
        super().__init__()
        self.setWindowTitle("MLX90640 Thermal Camera")
        self.setMinimumSize(820, 580)
        self.setStyleSheet(_STYLESHEET)

        # -- state -------------------------------------------------------------
        self._port     = self.DEFAULT_PORT
        self._baud     = self.DEFAULT_BAUD
        self._save_dir = self.DEFAULT_SAVEDIR
        self._lut      = COLORMAPS["Inferno"]
        self._gain     = 1.0
        self._interp   = True
        self._last_frame: np.ndarray | None = None
        self._last_rgba:  np.ndarray | None = None  # rendered frame for PNG save
        self._recorder = SequenceRecorder()
        self._reader:  FrameReader | None = None
        self._thread:  QThread     | None = None

        pathlib.Path(self._save_dir).mkdir(parents=True, exist_ok=True)

        self._build_menu()
        self._build_ui()
        # Auto-connect after window is shown
        QTimer.singleShot(200, self._connect_start)

    # -- menu ------------------------------------------------------------------

    def _build_menu(self):
        mb = self.menuBar()
        mb.setNativeMenuBar(False)

        # File
        fm = mb.addMenu("File")
        self._act_save_png = QAction("Save frame as PNG", self)
        self._act_save_csv = QAction("Save frame as CSV", self)
        self._act_save_npz = QAction("Save frame as NPZ", self)
        act_quit = QAction("Quit", self)
        for a in (self._act_save_png, self._act_save_csv, self._act_save_npz):
            a.setEnabled(False)
            fm.addAction(a)
        fm.addSeparator()
        fm.addAction(act_quit)

        self._act_save_png.triggered.connect(self._save_png)
        self._act_save_csv.triggered.connect(self._save_csv)
        self._act_save_npz.triggered.connect(self._save_npz)
        act_quit.triggered.connect(self.close)

        # Connection
        cm = mb.addMenu("Connection")
        self._act_connect    = QAction("Connect",    self)
        self._act_disconnect = QAction("Disconnect", self)
        self._act_settings   = QAction("Settings...", self)
        self._act_disconnect.setEnabled(False)
        cm.addAction(self._act_connect)
        cm.addAction(self._act_disconnect)
        cm.addSeparator()
        cm.addAction(self._act_settings)

        self._act_connect.triggered.connect(self._connect_start)
        self._act_disconnect.triggered.connect(self._connect_stop)
        self._act_settings.triggered.connect(self._open_settings)

        # Help
        hm = mb.addMenu("Help")
        act_about = QAction("About", self)
        act_about.triggered.connect(self._show_about)
        hm.addAction(act_about)

    # -- UI --------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # -- left: image + colorbar --------------------------------------------
        left = QVBoxLayout()
        left.setSpacing(4)

        self._img_widget = pg.GraphicsLayoutWidget()
        self._img_widget.setMinimumSize(512, 384)
        vb = self._img_widget.addViewBox()
        vb.setAspectLocked(True)
        vb.setMouseEnabled(False, False)
        vb.invertY(False)

        self._img_item = pg.ImageItem()
        vb.addItem(self._img_item)

        # crosshair
        self._crosshair_h = pg.InfiniteLine(angle=0, pen=pg.mkPen("#ffffff40", width=1))
        self._crosshair_v = pg.InfiniteLine(angle=90, pen=pg.mkPen("#ffffff40", width=1))
        vb.addItem(self._crosshair_h)
        vb.addItem(self._crosshair_v)
        self._img_item.scene().sigMouseMoved.connect(self._on_mouse_move)
        self._vb = vb

        self._colorbar = ColorbarWidget()

        left.addWidget(self._img_widget, stretch=1)
        left.addWidget(self._colorbar)

        # -- right: controls ---------------------------------------------------
        right = QVBoxLayout()
        right.setSpacing(8)
        right.setContentsMargins(0, 0, 0, 0)

        # Stats
        stats_box = QGroupBox("Statistics")
        stats_lay = QVBoxLayout(stats_box)
        stats_lay.setSpacing(4)
        self._lbl_min  = self._stat_label("Min")
        self._lbl_max  = self._stat_label("Max")
        self._lbl_avg  = self._stat_label("Avg")
        self._lbl_fps  = self._stat_label("FPS")
        self._lbl_cur  = self._stat_label("Cursor")
        for w in (self._lbl_min, self._lbl_max, self._lbl_avg,
                  self._lbl_fps, self._lbl_cur):
            stats_lay.addWidget(w)

        # Colormap
        cmap_box = QGroupBox("Colormap")
        cmap_lay = QVBoxLayout(cmap_box)
        self._cmap_combo = QComboBox()
        self._cmap_combo.addItems(list(COLORMAPS.keys()))
        cmap_lay.addWidget(self._cmap_combo)
        self._cmap_combo.currentTextChanged.connect(self._on_cmap_change)

        # Interpolation
        interp_box = QGroupBox("Interpolation")
        interp_lay = QVBoxLayout(interp_box)
        self._interp_combo = QComboBox()
        self._interp_combo.addItems(["Bilinear", "Nearest"])
        interp_lay.addWidget(self._interp_combo)
        self._interp_combo.currentTextChanged.connect(self._on_interp_change)

        # Gain
        gain_box = QGroupBox("Gain")
        gain_lay = QVBoxLayout(gain_box)
        self._gain_slider = QSlider(Qt.Orientation.Horizontal)
        self._gain_slider.setRange(5, 30)
        self._gain_slider.setValue(10)
        self._gain_lbl = QLabel("1.0 x")
        self._gain_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._gain_lbl.setStyleSheet("color: {};".format(_PAL["accent"]))
        gain_lay.addWidget(self._gain_slider)
        gain_lay.addWidget(self._gain_lbl)
        self._gain_slider.valueChanged.connect(self._on_gain_change)

        # Record
        rec_box = QGroupBox("Record sequence")
        rec_lay = QVBoxLayout(rec_box)
        self._rec_btn   = QPushButton("Record")
        self._rec_btn.setObjectName("rec_btn")
        self._rec_count = QLabel("0 frames")
        self._rec_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rec_count.setStyleSheet("color: {};".format(_PAL["muted"]))
        rec_lay.addWidget(self._rec_btn)
        rec_lay.addWidget(self._rec_count)
        self._rec_btn.clicked.connect(self._toggle_record)

        # Save frame
        save_box = QGroupBox("Save frame")
        save_lay = QVBoxLayout(save_box)
        for label, slot in (("PNG", self._save_png),
                             ("CSV", self._save_csv),
                             ("NPZ", self._save_npz)):
            btn = QPushButton(label)
            btn.clicked.connect(slot)
            save_lay.addWidget(btn)
            setattr(self, "_save_{}_btn".format(label.lower()), btn)
            btn.setEnabled(False)

        right.addWidget(stats_box)
        right.addWidget(cmap_box)
        right.addWidget(interp_box)
        right.addWidget(gain_box)
        right.addWidget(rec_box)
        right.addWidget(save_box)
        right.addStretch()

        root.addLayout(left, stretch=1)
        right_widget = QWidget()
        right_widget.setFixedWidth(180)
        right_widget.setLayout(right)
        root.addWidget(right_widget)

        # status bar
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("Disconnected")

        # FPS timer
        self._fps_counter = 0
        self._fps_timer = QTimer(self)
        self._fps_timer.timeout.connect(self._update_fps)
        self._fps_timer.start(1000)

    def _stat_label(self, name):
        w = QLabel("{}: --".format(name))
        w.setStyleSheet("color: {}; padding: 1px 0;".format(_PAL["text"]))
        return w

    # -- connection ------------------------------------------------------------

    def _connect_start(self):
        if self._thread and self._thread.isRunning():
            return

        self._act_connect.setEnabled(False)
        self._act_disconnect.setEnabled(True)

        self._reader = FrameReader(self._port, self._baud)
        self._thread = QThread()
        self._reader.moveToThread(self._thread)

        self._reader.frame_ready.connect(self._on_frame)
        self._reader.error.connect(self._on_error)
        self._reader.connected.connect(self._on_connected)
        self._reader.disconnected.connect(self._on_disconnected)

        self._thread.started.connect(self._reader.start)
        self._thread.start()

        self._act_connect.setEnabled(False)
        self._act_disconnect.setEnabled(True)

    def _connect_stop(self):
        if self._reader:
            self._reader.stop()
        if self._thread:
            self._thread.quit()
            self._thread.wait(3000)
        self._act_connect.setEnabled(True)
        self._act_disconnect.setEnabled(False)

    def _open_settings(self):
        dlg = SettingsDialog(self._port, self._baud, self._save_dir, self)
        dlg.setStyleSheet(self.styleSheet())
        if dlg.exec():
            port, baud, save_dir = dlg.values()
            changed = (port != self._port or baud != self._baud)
            self._port, self._baud, self._save_dir = port, baud, save_dir
            pathlib.Path(self._save_dir).mkdir(parents=True, exist_ok=True)
            if changed:
                self._connect_stop()
                self._connect_start()

    # -- frame handling --------------------------------------------------------

    @pyqtSlot(object)
    def _on_frame(self, frame: np.ndarray):
        self._last_frame = frame
        self._fps_counter += 1

        if self._recorder.recording:
            self._recorder.add_frame(frame)
            self._rec_count.setText("{} frames".format(self._recorder.frame_count))

        mn, mx = float(frame.min()), float(frame.max())
        avg    = float(frame.mean())
        rng    = mx - mn if mx != mn else 1.0

        # Normalise
        norm = np.clip((frame - mn) / rng * 255 * self._gain, 0, 255).astype(np.uint8)

        # Apply LUT -> RGBA
        rgba = np.zeros((*norm.shape, 4), dtype=np.uint8)
        rgba[..., :3] = self._lut[norm]
        rgba[...,  3] = 255

        # Interpolation
        if self._interp:
            from PyQt6.QtGui import QImage, QPixmap, QTransform
            h, w = rgba.shape[:2]
            img = QImage(rgba.tobytes(), w, h, w * 4, QImage.Format.Format_RGBA8888)
            # upscale with smooth transform via pixmap
            pm = QPixmap.fromImage(img).scaled(
                w * 16, h * 16,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            # convert back to numpy for pyqtgraph
            img2 = pm.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
            ptr  = img2.bits()
            ptr.setsize(img2.sizeInBytes())
            rgba = np.frombuffer(ptr, dtype=np.uint8).reshape(
                img2.height(), img2.width(), 4).copy()

        self._img_item.setImage(rgba.transpose(1, 0, 2))
        self._last_rgba = rgba

        self._colorbar.update_range(mn, mx)
        self._lbl_min.setText("Min: {:.2f} C".format(mn))
        self._lbl_max.setText("Max: {:.2f} C".format(mx))
        self._lbl_avg.setText("Avg: {:.2f} C".format(avg))

        for btn in (self._save_png_btn, self._save_csv_btn, self._save_npz_btn):
            btn.setEnabled(True)
        for act in (self._act_save_png, self._act_save_csv, self._act_save_npz):
            act.setEnabled(True)

    def _update_fps(self):
        self._lbl_fps.setText("FPS: {}".format(self._fps_counter))
        self._fps_counter = 0

    @pyqtSlot(str)
    def _on_connected(self, info):
        self._status.showMessage("Connected: {}".format(info))

    @pyqtSlot()
    def _on_disconnected(self):
        self._status.showMessage("Disconnected")

    @pyqtSlot(str)
    def _on_error(self, msg):
        self._status.showMessage("Error: {}".format(msg))
        self._act_connect.setEnabled(True)
        self._act_disconnect.setEnabled(False)

    # -- controls --------------------------------------------------------------

    def _on_cmap_change(self, name):
        self._lut = COLORMAPS[name]
        self._colorbar.set_lut(self._lut)

    def _on_interp_change(self, name):
        self._interp = (name == "Bilinear")

    def _on_gain_change(self, val):
        self._gain = val / 10.0
        self._gain_lbl.setText("{:.1f} x".format(self._gain))

    def _on_mouse_move(self, pos):
        if self._last_frame is None:
            return
        mapped = self._vb.mapSceneToView(pos)
        frame  = self._last_frame
        h, w   = frame.shape

        # In bilinear mode the image is 16x upscaled; normalise back to 32x24
        img_h, img_w = self._img_item.image.shape[:2] if self._img_item.image is not None else (h, w)
        scale_x = img_w / w
        scale_y = img_h / h

        col = int(mapped.x() / scale_x)
        row = int(mapped.y() / scale_y)

        if 0 <= col < w and 0 <= row < h:
            self._crosshair_h.setPos(mapped.y())
            self._crosshair_v.setPos(mapped.x())
            self._lbl_cur.setText("Cursor: {:.2f} C".format(frame[row, col]))

    # -- save ------------------------------------------------------------------

    def _save_png(self):
        if self._last_rgba is None:
            return
        from PyQt6.QtGui import QImage
        import pathlib, datetime
        rgba = np.ascontiguousarray(self._last_rgba[::-1])
        h, w, _ = rgba.shape
        img = QImage(rgba.data, w, h, w * 4, QImage.Format.Format_RGBA8888).copy()
        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = str(pathlib.Path(self._save_dir) / "frame_{}.png".format(ts))
        img.save(path)
        self._status.showMessage("Saved: {}".format(path), 4000)

    def _save_csv(self):
        if self._last_frame is None:
            return
        path = save_frame_csv(self._last_frame, self._save_dir)
        self._status.showMessage("Saved: {}".format(path), 4000)

    def _save_npz(self):
        if self._last_frame is None:
            return
        path = save_frame_npz(self._last_frame, self._save_dir)
        self._status.showMessage("Saved: {}".format(path), 4000)

    # -- record ----------------------------------------------------------------

    def _toggle_record(self):
        if self._recorder.recording:
            path = self._recorder.stop(self._save_dir)
            self._rec_btn.setText("Record")
            self._rec_btn.setProperty("recording", "false")
            self._rec_btn.style().unpolish(self._rec_btn)
            self._rec_btn.style().polish(self._rec_btn)
            self._rec_count.setText("0 frames")
            self._status.showMessage("Sequence saved: {}".format(path), 5000)
        else:
            self._recorder.start()
            self._rec_btn.setText("Stop")
            self._rec_btn.setProperty("recording", "true")
            self._rec_btn.style().unpolish(self._rec_btn)
            self._rec_btn.style().polish(self._rec_btn)

    # -- about -----------------------------------------------------------------

    def _show_about(self):
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.about(self, "About",
            "MLX90640 Thermal Camera Viewer\n"
            "GY-MCU90640 / AT32F415 bridge\n\n"
            "UAM Iztapalapa -- LINI\n"
            "M.Sc. Oscar Yanez Suarez\n\n"
            "GPL-3.0"
        )

    # -- close -----------------------------------------------------------------

    def closeEvent(self, event):
        if self._recorder.recording:
            self._recorder.discard()
        self._connect_stop()
        event.accept()
