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
from .constants import (
    DEFAULT_FIT_VIEW_MARGIN,
    MAX_NODE_GRAPH_DEPTH,
    SPLINE_COLOR,
    UIColors,
)
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

        self.fitViewMargin = DEFAULT_FIT_VIEW_MARGIN
        self.hideScrollbars = False

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

        if rect.isEmpty():  # also guards a 0-width/height rect
            return

        margin = self.fitViewMargin  # desired margin, in viewport pixels

        viewport = self.viewport().rect()
        availWidth = viewport.width() - 2.0 * margin
        availHeight = viewport.height() - 2.0 * margin
        if availWidth <= 0.0 or availHeight <= 0.0:
            return

        fitScale = min(
            availWidth / rect.width(),
            availHeight / rect.height(),
        )

        # Viewport pixels -> scene units at the scale fitInView will apply.
        sceneMargin = margin / fitScale

        rect.adjust(-sceneMargin, -sceneMargin, sceneMargin, sceneMargin)
        self.fitInView(rect, QtCore.Qt.KeepAspectRatio)

    def GetFitViewMargin(self):
        return self.fitViewMargin

    def SetFitViewMargin(self, margin):
        self.fitViewMargin = max(0.0, float(margin))

    def GetHideScrollbars(self):
        return self.hideScrollbars

    def SetHideScrollbars(self, hide):
        self.hideScrollbars = bool(hide)
        policy = (
            QtCore.Qt.ScrollBarAlwaysOff
            if self.hideScrollbars
            else QtCore.Qt.ScrollBarAsNeeded
        )
        self.setHorizontalScrollBarPolicy(policy)
        self.setVerticalScrollBarPolicy(policy)

    def drawBackground(self, painter, rect):
        # Fill background; needed for HW acceleleration
        viewportRect = self.viewport().rect()
        sceneRect = self.mapToScene(viewportRect).boundingRect()
        painter.fillRect(sceneRect, QtGui.QColor(UIColors.CHARCOAL))

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

        self.selectedNodes = []
        self.nodeFilterTargets = {}
        self.primNodeMap = {}
        self.parentNgNodeMap = {}
        self.scene = None
        self.graphRoot = None
        self.showAllOutputPorts = False
        self.portMarkers = []
        self.portMarkerNodeMap = {}
        self.portMarkerUpdatePending = False

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

        def AddNodeToColumn(node, columnIndex):
            node.setZValue(1)  # Render nodes on top of lines
            columns[columnIndex].addItem(node)
            self.CreatePortMarkers(node)
            return node

        # Insert the node representing the parent node graph inputs
        for ngPrim, (depth, inputNames) in self.parentNgInputMap.items():
            nodeGraph = UsdShade.NodeGraph(ngPrim)
            ngInputs = [nodeGraph.GetInput(name) for name in inputNames]
            node = MakeNgInputNode(nodeGraph, ngInputs)

            columnIndex = maxDepth - depth - 1
            self.parentNgNodeMap[ngPrim] = AddNodeToColumn(
                node, columnIndex
            )

        # Insert all previously traversed nodes
        for prim, depth in self.nodeMap.items():
            if prim == directParentPrim:
                nodeGraph = UsdShade.NodeGraph(prim)
                outputs = nodeGraph.GetOutputs()
                node = MakeNgOutputNode(prim, outputs)
            else:
                node = MakeSdrShaderNode(
                    prim, self.ngChangeCallback, self.showAllOutputPorts
                )

            columnIndex = maxDepth - depth - 1

            self.primNodeMap[prim] = AddNodeToColumn(node, columnIndex)

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

            if upstreamPrim in self.parentNgNodeMap:
                startNode = self.parentNgNodeMap[upstreamPrim]
            else:
                startNode = self.primNodeMap[upstreamPrim]

            outputPortName = source[1]
            endNode = self.primNodeMap[prim]
            inputPortName = port.GetBaseName()

            line = SplineConnectionWidget(
                startNode, outputPortName, endNode, inputPortName
            )
            self.scene.addItem(line)

            # We stop traversal when we encounter a parent node graph
            if upstreamPrim in self.parentNgNodeMap:
                continue

            upstreamInputs = self.GetShadePrimInputs(upstreamPrim)

            self.AddNodeConnections(upstreamPrim, upstreamInputs, depth + 1)

    def PopulateScene(self, nodeGraph, selectedOutput):
        self.ClearSelection()
        self.nodeFilterTargets.clear()

        self.nodeGraph = nodeGraph
        self.scene = QtWidgets.QGraphicsScene(self)
        self.portMarkers = []
        self.portMarkerNodeMap = {}

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
        self.parentNgNodeMap = {}  # [prim, node]
        self.BuildNodeMap(rootPrim, rootInputs, 0)

        self.primNodeMap = {}  # [prim, node]
        self.AddNodesToLayout()

        self.nodeMap = {}
        self.AddNodeConnections(rootPrim, rootInputs, 0)

        self.graphRoot = QtWidgets.QGraphicsWidget()
        self.graphRoot.setLayout(self.graphLayout)
        self.scene.addItem(self.graphRoot)

        self.SchedulePortMarkerUpdate()
        self.graphView.setScene(self.scene)
        self.UpdateNodeFilterTargets()

    def CreatePortMarkers(self, node):
        for portType, name in node.GetPortDescriptors():
            marker = QtWidgets.QGraphicsPolygonItem()
            marker.setPen(QtGui.QPen(QtCore.Qt.NoPen))
            marker.setBrush(QtGui.QColor(SPLINE_COLOR))
            marker.setAcceptedMouseButtons(QtCore.Qt.NoButton)
            marker.setZValue(2)
            self.scene.addItem(marker)
            self.portMarkers.append((node, portType, name, marker))
            self.portMarkerNodeMap[marker] = node

        node.geometryChanged.connect(self.SchedulePortMarkerUpdate)

    def SchedulePortMarkerUpdate(self):
        if self.portMarkerUpdatePending:
            return

        self.portMarkerUpdatePending = True
        QtCore.QTimer.singleShot(0, self.UpdatePortMarkersOnIdle)

    def UpdatePortMarkersOnIdle(self):
        self.portMarkerUpdatePending = False
        self.UpdatePortMarkers()

    def UpdatePortMarkers(self):
        for node, portType, name, marker in self.portMarkers:
            size = node.PORT_TRIANGLE_SIZE
            half = size / 2.0
            position = node.mapToScene(node.GetPortPosition(name, portType))
            x = position.x() - half
            marker.setPolygon(
                QtGui.QPolygonF(
                    [
                        QtCore.QPointF(x, position.y() - half),
                        QtCore.QPointF(x, position.y() + half),
                        QtCore.QPointF(x + size, position.y()),
                    ]
                )
            )

    def GetAllNodes(self):
        return list(self.primNodeMap.values()) + list(
            self.parentNgNodeMap.values()
        )

    def UpdateNodeFilterTargets(self):
        for node in self.GetAllNodes():
            self.nodeFilterTargets[node.body] = node
            for child in node.body.findChildren(QtWidgets.QWidget):
                self.nodeFilterTargets[child] = node

    def UpdateSelectionStyles(self):
        for node in self.GetAllNodes():
            node.SetSelected(node in self.selectedNodes)

    def ClearSelection(self):
        if self.selectedNodes:
            self.selectedNodes = []
            self.UpdateSelectionStyles()

    def SelectNode(self, node, modifiers):
        if not (modifiers & QtCore.Qt.ShiftModifier):
            self.selectedNodes = [node]
        elif node in self.selectedNodes:
            self.selectedNodes.remove(node)
        else:
            self.selectedNodes.append(node)

        self.UpdateSelectionStyles()

    def FrameSelected(self):
        self.FrameNodes(self.selectedNodes)

    def FrameAll(self):
        self.FrameNodes(self.GetAllNodes())

    def ZoomIn(self):
        self.graphView.ZoomIn()

    def ZoomOut(self):
        self.graphView.ZoomOut()

    def GetFitViewMargin(self):
        return self.graphView.GetFitViewMargin()

    def SetFitViewMargin(self, margin):
        self.graphView.SetFitViewMargin(margin)

    def GetHideScrollbars(self):
        return self.graphView.GetHideScrollbars()

    def SetHideScrollbars(self, hide):
        self.graphView.SetHideScrollbars(hide)

    def GetShowAllOutputPorts(self):
        return self.showAllOutputPorts

    def SetShowAllOutputPorts(self, show):
        self.showAllOutputPorts = bool(show)

    def FrameNodes(self, nodes):
        if self.scene is None:
            return

        nodes = [n for n in nodes if n.scene() is self.scene]
        if nodes:
            self.graphView.FrameItems(nodes)

    def GetNodeForItem(self, item):
        while item is not None and not isinstance(item, GraphNode):
            item = item.parentItem()
        return item

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
                node = self.portMarkerNodeMap.get(item)
                if node is None:
                    node = self.GetNodeForItem(item)
                if node is not None:
                    self.SelectNode(node, event.modifiers())
                else:
                    self.ClearSelection()

        return super().eventFilter(obj, event)
