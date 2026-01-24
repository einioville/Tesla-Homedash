# Needed to be imported for other modules to be able to access some dlls
if __name__ == "__main__":
    from PySide6.QtCore import Qt

import pyqtgraph as pg
from PySide6.QtWidgets import QFrame, QVBoxLayout
from PySide6.QtCore import Slot
from PySide6.QtGui import QLinearGradient, QBrush
import numpy as np


class DataPlot(QFrame):
    """
    Used to make interactive plots from vehicle data

    Args:

    """

    def __init__(self, title: str, x_range: tuple, y_range: tuple) -> None:
        super().__init__()

        self.__layout = QVBoxLayout()
        self.__layout.setContentsMargins(5, 5, 5, 5)
        self.setLayout(self.__layout)

        self.__graph = pg.GraphicsLayoutWidget()
        self.__graph.viewport().setMouseTracking(True)
        self.__layout.addWidget(self.__graph)

        self.__x_range = x_range
        self.__y_range = y_range

        self.__plot = self.__graph.addPlot()
        self.__plot.setTitle(title)
        self.__plot.setRange(xRange=x_range, yRange=y_range)
        self.__plot.setMenuEnabled(False)
        self.__plot.setMouseEnabled(x=False, y=False)
        self.__plot.hideButtons()
        self.__plot.scene().sigMouseMoved.connect(self.__on_mouse_moved)

        self.__crosshair_x = pg.InfiniteLine(
            pos=(0, 0), angle=90, pen=pg.mkPen("orange")
        )
        self.__crosshair_x.setZValue(1)
        self.__plot.addItem(
            self.__crosshair_x,
        )

        self.__crosshair_y = pg.InfiniteLine(
            pos=(0, 0), angle=0, pen=pg.mkPen("orange")
        )
        self.__crosshair_y.setZValue(1)
        self.__plot.addItem(self.__crosshair_y)

        self.__x_value = pg.TextItem(
            text="",
            color="white",
            anchor=(0.5, 0.5),
            border=pg.mkPen("orange"),
            fill=pg.mkBrush("black"),
        )
        self.__x_value.setZValue(2)
        self.__plot.addItem(self.__x_value)

        self.__y_value = pg.TextItem(
            text="",
            color="white",
            anchor=(-0.25, 0.5),
            border=pg.mkPen("orange"),
            fill=pg.mkBrush("black"),
        )
        self.__y_value.setZValue(2)
        self.__plot.addItem(self.__y_value)

        self.__gradient = QLinearGradient(0, 1 * y_range[0], 0, 1 * y_range[1])
        self.__gradient.setColorAt(1, pg.mkColor("red"))
        self.__gradient.setColorAt(0.5, pg.mkColor((255, 255, 0, 15)))
        self.__gradient.setColorAt(0.0, pg.mkColor("green"))
        self.__brush = QBrush(self.__gradient)

        self.__x_data = np.linspace(start=-5, stop=5, num=1000)
        self.__y_data = 50 * np.cos(5 * self.__x_data)
        self.__y_data[400:600] = self.__y_data[400:600] * 2
        self.__plot.plot(
            self.__x_data,
            self.__y_data,
            pen=pg.mkPen(color="orange", width=1),
            brush=self.__brush,
            fillLevel=0,
        )

    @Slot(tuple)
    def __on_mouse_moved(self, pos):
        mouse_point = self.__plot.vb.mapSceneToView(pos)
        closest_index = np.abs(self.__x_data - mouse_point.x()).argmin()

        x_value = self.__x_data[closest_index]
        y_value = self.__y_data[closest_index]

        self.__x_value.setText(str(x_value))
        self.__y_value.setText(str(y_value))
        self.__crosshair_x.setPos(x_value)
        self.__crosshair_y.setPos(y_value)
        self.__x_value.setPos(x_value, self.__y_range[0])
        self.__y_value.setPos(x_value, y_value)

        y_value_width = (
            self.__plot.vb.mapSceneToView(
                self.__y_value.mapToScene(self.__y_value.boundingRect().width(), 0)
            ).x()
            - x_value
        )

        if self.__y_value.anchor[0] == -0.25:
            if x_value - y_value_width * -1.25 >= self.__x_range[1]:
                self.__y_value.setAnchor((1.25, 0.5))

        else:
            if x_value - y_value_width * 1.25 <= self.__x_range[0]:
                self.__y_value.setAnchor((-0.25, 0.5))


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication

    app = QApplication()
    dataplot = DataPlot(title="Test", x_range=(-5, 5), y_range=(-100, 100))
    dataplot.show()
    app.exec()
