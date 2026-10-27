#
# Copyright 2025 Pablo Delgado Krämer
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""Graph connection rendering."""

from pxr.Usdviewq.qt import QtCore, QtGui, QtWidgets

from .constants import SPLINE_COLOR, PortType


class ConnectionWidget:
    def __init__(self, startNode, outputName, endNode, inputName):
        super().__init__()
        self.startNode = startNode
        self.endNode = endNode
        self.outputName = outputName
        self.inputName = inputName

        self.startNode.geometryChanged.connect(self.UpdateGeometry)
        self.endNode.geometryChanged.connect(self.UpdateGeometry)

        self.setPen(QtGui.QPen(QtGui.QColor(SPLINE_COLOR), 1.0))
        self.UpdateGeometry()

    def UpdateGeometry(self):
        outputPos = self.startNode.GetPortPosition(
            self.outputName, PortType.OUTPUT
        )
        inputPos = self.endNode.GetPortPosition(
            self.inputName, PortType.INPUT
        )

        startPos = self.startNode.mapToScene(outputPos)
        endPos = self.endNode.mapToScene(inputPos)

        self.SetStartEndPoints(startPos, endPos)


# Bezier spline
class SplineConnectionWidget(ConnectionWidget, QtWidgets.QGraphicsPathItem):
    def SetStartEndPoints(self, p1, p2):
        path = QtGui.QPainterPath()

        dx = p2.x() - p1.x()

        eps = 0.01
        if abs(dx) < eps:
            dx = eps if dx >= 0 else -eps

        C = 0.5
        controlPoint1 = QtCore.QPointF(p1.x() + dx * C, p1.y())
        controlPoint2 = QtCore.QPointF(p2.x() - dx * C, p2.y())

        path.moveTo(p1)
        path.cubicTo(controlPoint1, controlPoint2, p2)

        self.setPath(path)
