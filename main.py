# SPDX-License-Identifier: GPL-3.0-or-later
# MLX90640 Thermal Camera Viewer
# UAM Iztapalapa -- LINI
# M.Sc. Oscar Yanez Suarez

import sys
from PyQt6.QtWidgets import QApplication
from thermal_cam.app import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Thermal Camera")
    app.setOrganizationName("LINI-UAM")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
