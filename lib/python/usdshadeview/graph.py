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

"""Graph scene, layout and interactive view."""

import sys

from pxr import UsdShade
from pxr.Usdviewq.qt import QGLFormat, QGLWidget, QtCore, QtGui, QtWidgets

from .compat import PySideModule, enableHwAcceleration
from .connections import SplineConnectionWidget
from .constants import MAX_NODE_GRAPH_DEPTH, UIColors
from .nodes import (
    GraphNode,
    MakeNgInputNode,
    MakeNgOutputNode,
    MakeSdrShaderNode,
)


class GraphView(QtWidgets.QGraphicsView):
    MIN_SCALE = 0.05
    MAX_SCALE = 20.0
    KEY_ZOOM_STEP = 1.2

    def __init__(self):
        super().__init__()

        self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self.setRenderHints(
            QtGui.QPainter.Antialiasing
            | QtGui.QPainter.TextAntialiasing
            | QtGui.QPainter.SmoothPixmapTransform
        )
        # Fix background not updating when window is hovering on top
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.FullViewportUpdate)

        # HW acceleration greatly speeds up spline rendering and has better AA
        if enableHwAcceleration:
            glFormat = QGLFormat()
            glFormat.setSamples(8)  # MSAA
            if PySideModule != "PySide6":
                glFormat.setSampleBuffers(True)

            if PySideModule == "PySide6":
                glWidget = QGLWidget()
                glWidget.setFormat(glFormat)
            else:
                glWidget = QGLWidget(glFormat)

            self.setViewport(glWidget)

    def ZoomIn(self):
        self.ZoomBy(self.KEY_ZOOM_STEP)

    def ZoomOut(self):
        self.ZoomBy(1.0 / self.KEY_ZOOM_STEP)

    def ZoomBy(self, factor, anchor=None):
        currentScale = self.transform().m11()
        if currentScale <= 0.0:
            return

        targetScale = currentScale * factor
        if targetScale < self.MIN_SCALE:
            factor = self.MIN_SCALE / currentScale
        elif targetScale > self.MAX_SCALE:
            factor = self.MAX_SCALE / currentScale

        if abs(factor - 1.0) < 1e-6:
            return

        if anchor is None:
            anchor = self.viewport().rect().center()

        oldPos = self.mapToScene(anchor)
        self.scale(factor, factor)

        # Scroll so the scene point under the anchor stays in place.
        newViewPos = self.mapFromScene(oldPos)
        delta = newViewPos - anchor
        self.ScrollBy(delta.x(), delta.y())

    def ScrollBy(self, dx, dy):
        hBar = self.horizontalScrollBar()
        vBar = self.verticalScrollBar()
        hBar.setValue(hBar.value() + dx)
        vBar.setValue(vBar.value() + dy)

    def wheelEvent(self, event):
        pixelDelta = event.pixelDelta().y()
        angleDelta = event.angleDelta().y()

        if angleDelta != 0:
            factor = 1.0015**angleDelta
        elif pixelDelta != 0:
            factor = 1.005**pixelDelta
        else:
            event.ignore()
            return

        # Keep trackpad momentum from jumping the zoom level too far.
        factor = max(0.8, min(1.25, factor))

        if hasattr(event, "position"):
            anchor = event.position().toPoint()
        else:
            anchor = event.pos()

        self.ZoomBy(factor, anchor)
        event.accept()

    def FrameItems(self, items):
        rect = QtCore.QRectF()
        for item in items:
            rect = rect.united(item.sceneBoundingRect())

        if rect.isEmpty():
            return

        margin = 40.0
        rect.adjust(-margin, -margin, margin, margin)
        self.fitInView(rect, QtCore.Qt.KeepAspectRatio)

    def drawBackground(self, painter, rect):
        # Fill background; needed for HW acceleleration
        viewportRect = self.viewport().rect()
        sceneRect = self.mapToScene(viewportRect).boundingRect()
        painter.fillRect(sceneRect, QtGui.QColor("#383838"))

        # Draw grid lines
        lineColor = QtGui.QColor(UIColors.DARK_GREY)
        painter.setPen(lineColor)
        lineSpacing = 28

        # Snap lines to scene-space multiples so the grid moves with the
        # nodes instead of following the viewport.
        lineX = rect.left() - rect.left() % lineSpacing
        while lineX < rect.right():
            painter.drawLine(lineX, rect.bottom(), lineX, rect.top())
            lineX += lineSpacing

        lineY = rect.top() - rect.top() % lineSpacing
        while lineY < rect.bottom():
            painter.drawLine(rect.left(), lineY, rect.right(), lineY)
            lineY += lineSpacing


class GraphWidget(QtWidgets.QWidget):
    def __init__(self, ngChangeCallback):
        super().__init__()

        self.ngChangeCallback = ngChangeCallback

        self.selectedProxies = []
        self.nodeFilterTargets = {}
        self.widgetMap = {}
        self.parentNgWidgetMap = {}
        self.scene = None

        self.graphView = GraphView()

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.graphView)
        self.setLayout(layout)

        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def RenderSceneToImage(self):
        scaleFactor = 4.0  # Higher values = larger resolution = less aliasing

        self.scene.clearSelection()
        self.scene.setSceneRect(self.scene.itemsBoundingRect())

        imageSize = self.scene.sceneRect().size().toSize()
        image = QtGui.QImage(
            imageSize * scaleFactor, QtGui.QImage.Format_ARGB32
        )
        image.fill(QtCore.Qt.transparent)

        painter = QtGui.QPainter(image)
        self.scene.render(painter)
        painter.end()

        return image

    # Store the nodes we encounter during traversal and their maximum depth
    def UpdateNodeDepth(self, prim, depth):
        if prim in self.nodeMap:
            oldDepth = self.nodeMap[prim]

            # Already visited, abort traversal (optimization)
            if depth <= oldDepth:
                return False

            depth = max(oldDepth, depth)

        self.nodeMap[prim] = depth
        self.maxDepth = max(self.maxDepth, depth)
        return True

    # Returns the UsdShade.Input list of shaders and node graph prims
    def GetShadePrimInputs(self, prim):
        if prim.IsA(UsdShade.Shader):
            shader = UsdShade.Shader(prim)
            return shader.GetInputs()

        elif prim.IsA(UsdShade.NodeGraph):
            nodeGraph = UsdShade.NodeGraph(prim)
            return nodeGraph.GetInputs()

        return []  # (should not happen)

    # Traverses the node graph hierarchy until we're outside of the UsdShade network
    # and checks if any of the parent node graph prims matches our prim.
    def IsParentNodeGraph(self, prim, directParentPrim):
        if prim == directParentPrim:
            return True

        parent = directParentPrim

        while parent.IsA(UsdShade.NodeGraph):
            if parent == prim:
                return True
            parent = parent.GetParent()

        return False

    # Traverse the given ports (outputs) to their leaf prims, and store all nodes along the way.
    # Note that the ports list can contain either UsdShade.Output (when we pass in the parent
    # node graph outputs) or UsdShade.Input (when we want to follow a node's input connections).
    # Furthermore we track which inputs from the parent node graph are used, and at which depth.
    def BuildNodeMap(self, prim, ports, depth):
        if depth > MAX_NODE_GRAPH_DEPTH:
            print("WARNING: maximum node graph depth reached", file=sys.stderr)
            return

        if not self.UpdateNodeDepth(prim, depth):
            return

        directParentPrim = self.nodeGraph.GetPrim()

        for port in ports:
            source = port.GetConnectedSource()

            if not source:
                continue

            connectableApi = source[0]

            upstreamPrim = connectableApi.GetPrim()
            if not upstreamPrim:
                continue

            # Check if this output is actually an input from a parent NG
            if self.IsParentNodeGraph(upstreamPrim, directParentPrim):
                if upstreamPrim in self.parentNgInputMap:
                    t = self.parentNgInputMap[upstreamPrim]
                else:
                    t = (0, set())  # depth, input name

                newDepth = max(depth + 1, t[0])
                newMap = t[1]
                newMap.add(source[1])

                self.maxDepth = max(self.maxDepth, newDepth)
                self.parentNgInputMap[upstreamPrim] = (newDepth, newMap)
                continue

            upstreamInputs = self.GetShadePrimInputs(upstreamPrim)

            self.BuildNodeMap(upstreamPrim, upstreamInputs, depth + 1)

    # In this function we create column layouts corresponding to the node graph's depth and
    # insert the node widgets into them at their respective depth. We also insert an extra
    # node to model the inputs coming from the parent node graph.
    def AddNodesToLayout(self):

        maxDepth = self.maxDepth + 1
        directParentPrim = self.nodeGraph.GetPrim()

        columns = [
            QtWidgets.QGraphicsLinearLayout(QtCore.Qt.Vertical)
            for _ in range(maxDepth)
        ]
        for column in columns:
            column.addStretch()

        def AddProxyWidgetToColumn(widget, columnIndex):
            proxy = QtWidgets.QGraphicsProxyWidget()
            proxy.setWidget(widget)
            proxy.setZValue(1)  # Render nodes on top of lines
            columns[columnIndex].addItem(proxy)
            return proxy

        # Insert the node representing the parent node graph inputs
        for ngPrim, (depth, inputNames) in self.parentNgInputMap.items():
            nodeGraph = UsdShade.NodeGraph(ngPrim)
            ngInputs = [nodeGraph.GetInput(name) for name in inputNames]
            w = MakeNgInputNode(nodeGraph, ngInputs)

            columnIndex = maxDepth - depth - 1
            self.parentNgWidgetMap[ngPrim] = AddProxyWidgetToColumn(
                w, columnIndex
            )

        # Insert all previously traversed nodes
        for prim, depth in self.nodeMap.items():
            if prim == directParentPrim:
                nodeGraph = UsdShade.NodeGraph(prim)
                outputs = nodeGraph.GetOutputs()
                w = MakeNgOutputNode(prim, outputs)
            else:
                w = MakeSdrShaderNode(prim, self.ngChangeCallback)

            columnIndex = maxDepth - depth - 1

            self.widgetMap[prim] = AddProxyWidgetToColumn(w, columnIndex)

        for i in range(0, maxDepth):
            column = columns[i]

            if column.count() == 0:
                continue  # Should only happen in the case of circular graphs

            column.addStretch()
            self.graphLayout.addItem(column)

    # Create connection widgets between upstream and downstream nodes. For this
    # we traverse the network again and get the widget for each prim using the map.
    def AddNodeConnections(self, prim, ports, depth):
        if depth > MAX_NODE_GRAPH_DEPTH:
            print("WARNING: maximum node graph depth reached", file=sys.stderr)
            return

        # We reuse the nodemap from the discovery phase to skip existing connections.
        if not self.UpdateNodeDepth(prim, depth):
            return

        for port in ports:
            source = port.GetConnectedSource()

            if not source:
                continue

            connectableApi = source[0]

            upstreamPrim = connectableApi.GetPrim()
            if not upstreamPrim:
                continue

            if upstreamPrim in self.parentNgWidgetMap:
                startNode = self.parentNgWidgetMap[upstreamPrim]
            else:
                startNode = self.widgetMap[upstreamPrim]

            outputPortName = source[1]
            endNode = self.widgetMap[prim]
            inputPortName = port.GetBaseName()

            line = SplineConnectionWidget(
                startNode, outputPortName, endNode, inputPortName
            )
            self.scene.addItem(line)

            # We stop traversal when we encounter a parent node graph
            if upstreamPrim in self.parentNgWidgetMap:
                continue

            upstreamInputs = self.GetShadePrimInputs(upstreamPrim)

            self.AddNodeConnections(upstreamPrim, upstreamInputs, depth + 1)

    def PopulateScene(self, nodeGraph, selectedOutput):
        self.ClearSelection()
        self.nodeFilterTargets.clear()

        self.nodeGraph = nodeGraph
        self.scene = QtWidgets.QGraphicsScene(self)

        rootPrim = nodeGraph.GetPrim()
        rootInputs = (
            nodeGraph.GetOutputs()
            if selectedOutput is None
            else [selectedOutput]
        )

        #
        # Our layouting algorithm is simple and has three steps:
        #
        # 1) Traverse the network (depth first) from the outputs to the leaf nodes in order
        #    to get a list of relevant nodes (culling) and the maximum depth of the graph.
        #
        # 2) Iterate over the nodes and insert them into columns based on their maximum depth.
        #
        # 3) Traverse the network again to create widgets for the node connections.
        #
        self.graphLayout = QtWidgets.QGraphicsLinearLayout(
            QtCore.Qt.Horizontal
        )
        self.graphLayout.setContentsMargins(22, 22, 22, 22)
        self.graphLayout.setSpacing(64)

        self.maxDepth = 0
        self.nodeMap = {}  # [prim, depth]
        self.parentNgInputMap = {}  # used parent node graph inputs
        self.parentNgWidgetMap = {}  # [prim, node widget]
        self.BuildNodeMap(rootPrim, rootInputs, 0)

        self.widgetMap = {}  # [prim, node widget]
        self.AddNodesToLayout()

        self.nodeMap = {}
        self.AddNodeConnections(rootPrim, rootInputs, 0)

        graphWidget = QtWidgets.QGraphicsWidget()
        graphWidget.setLayout(self.graphLayout)
        self.scene.addItem(graphWidget)

        self.graphView.setScene(self.scene)
        self.UpdateNodeFilterTargets()

    def GetAllNodeProxies(self):
        return list(self.widgetMap.values()) + list(
            self.parentNgWidgetMap.values()
        )

    def UpdateNodeFilterTargets(self):
        for proxy in self.GetAllNodeProxies():
            node = proxy.widget()
            if node is None:
                continue

            self.nodeFilterTargets[node] = proxy
            for child in node.findChildren(QtWidgets.QWidget):
                self.nodeFilterTargets[child] = proxy

    def UpdateSelectionStyles(self):
        for proxy in self.GetAllNodeProxies():
            node = proxy.widget()
            if isinstance(node, GraphNode):
                node.SetSelected(proxy in self.selectedProxies)

    def ClearSelection(self):
        if self.selectedProxies:
            self.selectedProxies = []
            self.UpdateSelectionStyles()

    def SelectNode(self, proxy, modifiers):
        if not (modifiers & QtCore.Qt.ShiftModifier):
            self.selectedProxies = [proxy]
        elif proxy in self.selectedProxies:
            self.selectedProxies.remove(proxy)
        else:
            self.selectedProxies.append(proxy)

        self.UpdateSelectionStyles()

    def FrameSelected(self):
        self.FrameNodes(self.selectedProxies)

    def FrameAll(self):
        self.FrameNodes(self.GetAllNodeProxies())

    def ZoomIn(self):
        self.graphView.ZoomIn()

    def ZoomOut(self):
        self.graphView.ZoomOut()

    def FrameNodes(self, proxies):
        if self.scene is None:
            return

        proxies = [p for p in proxies if p.scene() is self.scene]
        if proxies:
            self.graphView.FrameItems(proxies)

    def IsFrameKey(self, event):
        return event.key() in (
            QtCore.Qt.Key.Key_F,
            QtCore.Qt.Key.Key_A,
        ) and event.modifiers() in (
            QtCore.Qt.NoModifier,
            QtCore.Qt.KeypadModifier,
        )

    def IsZoomKey(self, event):
        zoomKeys = (
            QtCore.Qt.Key.Key_Plus,
            QtCore.Qt.Key.Key_Equal,
            QtCore.Qt.Key.Key_Minus,
            QtCore.Qt.Key.Key_Underscore,
        )
        return event.key() in zoomKeys and event.modifiers() in (
            QtCore.Qt.NoModifier,
            QtCore.Qt.ShiftModifier,
            QtCore.Qt.KeypadModifier,
        )

    def IsPanelKey(self, event):
        return self.IsFrameKey(event) or self.IsZoomKey(event)

    def IsKeyTarget(self, obj):
        if obj is self or obj is self.graphView:
            return True
        if obj is self.graphView.viewport():
            return True
        if obj in self.nodeFilterTargets:
            return True

        return self.IsGraphUnderMouse()

    def IsGraphUnderMouse(self):
        if QtWidgets.QApplication.activeModalWidget() is not None:
            return False

        widget = QtWidgets.QApplication.widgetAt(QtGui.QCursor.pos())
        if widget is None:
            return False

        return (
            widget is self.graphView.viewport()
            or widget in self.nodeFilterTargets
        )

    def HandleKeyPress(self, event):
        key = event.key()

        if key == QtCore.Qt.Key.Key_F:
            self.FrameSelected()
        elif key == QtCore.Qt.Key.Key_A:
            self.FrameAll()
        elif key in (QtCore.Qt.Key.Key_Plus, QtCore.Qt.Key.Key_Equal):
            self.ZoomIn()
        elif key in (QtCore.Qt.Key.Key_Minus, QtCore.Qt.Key.Key_Underscore):
            self.ZoomOut()

        return True

    def eventFilter(self, obj, event):
        eventType = event.type()

        if eventType == QtCore.QEvent.Type.ShortcutOverride:
            if self.IsPanelKey(event) and self.IsKeyTarget(obj):
                event.accept()
                return True
        elif eventType == QtCore.QEvent.Type.KeyPress:
            if self.IsPanelKey(event) and self.IsKeyTarget(obj):
                return self.HandleKeyPress(event)
        elif eventType == QtCore.QEvent.Type.MouseButtonPress:
            if (
                event.button() == QtCore.Qt.LeftButton
                and obj is self.graphView.viewport()
            ):
                item = self.graphView.itemAt(event.pos())
                if item in self.GetAllNodeProxies():
                    self.SelectNode(item, event.modifiers())
                else:
                    self.ClearSelection()

        return super().eventFilter(obj, event)
