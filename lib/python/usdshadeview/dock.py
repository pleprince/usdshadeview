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

"""The usdview dock widget and its persisted state."""

import base64
import platform
import sys

from pxr import UsdShade
from pxr.Usdviewq.qt import QtCore, QtGui, QtWidgets
from pxr.Usdviewq.settings import StateSource

from .compat import mtlxSupported
from .constants import (
    DEFAULT_FIT_VIEW_MARGIN,
    DEFAULT_NODE_VERTICAL_SPACING,
    DEFAULT_SHOW_NODE_GRAPH_SHORTCUT,
    GraphColors,
)
from .dialogs import BakeMtlxDialog, PreferencesDialog
from .graph import GraphWidget


class GraphDockWidget(QtWidgets.QDockWidget):
    DOCK_OBJECT_NAME = "usdshadeviewDock"
    DEFAULT_TITLE = "UsdShade Node Graph"

    showNodeGraphShortcutChanged = QtCore.Signal(str)

    def ShowBakeMtlxDialog(self):
        material = UsdShade.Material(self.nodeGraph)
        previousDialog = getattr(self, "bakeMtlxDialog", None)
        if previousDialog is not None:
            previousDialog.close()
            previousDialog.deleteLater()
        self.bakeMtlxDialog = BakeMtlxDialog(material, self)
        self.bakeMtlxDialog.show()

    def ShowExportAsImageDialog(self):
        # NOTE: on macOS there's an issue where the main window is incorrectly focused after close
        filePath, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save File",
            "graph.png",  # default dir = CWD
            "Images (*.png *.webp);;All Files (*)",
        )

        if filePath:
            image = self.graphWidget.RenderSceneToImage()
            image.save(filePath)

    def ShowPreferencesDialog(self):
        graphWidget = self.graphWidget
        graphView = graphWidget.graphView
        dialog = PreferencesDialog(
            self,
            graphView.GetFitViewMargin(),
            graphWidget.GetNodeVerticalSpacing(),
            graphView.GetHideScrollbars(),
            graphWidget.GetShowAllOutputPorts(),
            self.showNodeGraphShortcut,
            graphWidget.GetColors(),
        )
        try:
            if dialog.Run() != QtWidgets.QDialog.Accepted:
                return

            graphView.SetFitViewMargin(dialog.GetFitViewMargin())
            graphView.SetHideScrollbars(dialog.GetHideScrollbars())
            self.SetShowNodeGraphShortcut(dialog.GetShowNodeGraphShortcut())

            nodeVerticalSpacing = dialog.GetNodeVerticalSpacing()
            spacingChanged = (
                nodeVerticalSpacing != graphWidget.GetNodeVerticalSpacing()
            )
            graphWidget.SetNodeVerticalSpacing(nodeVerticalSpacing)

            colors = dialog.GetColors()
            colorsChanged = colors != graphWidget.GetColors()
            graphWidget.SetColors(colors)

            showAllOutputPorts = dialog.GetShowAllOutputPorts()
            if (
                showAllOutputPorts == graphWidget.GetShowAllOutputPorts()
                and not spacingChanged
                and not colorsChanged
            ):
                return

            graphWidget.SetShowAllOutputPorts(showAllOutputPorts)
            if self.nodeGraph is not None:
                self.UpdateContentForOutput()
        finally:
            dialog.deleteLater()

    def GetShowNodeGraphShortcut(self):
        return self.showNodeGraphShortcut

    def SetShowNodeGraphShortcut(self, shortcut):
        if shortcut == self.showNodeGraphShortcut:
            return
        self.showNodeGraphShortcut = shortcut
        self.showNodeGraphShortcutChanged.emit(shortcut)

    def AddViewAction(self, menu, text, shortcut, callback):
        action = menu.addAction(text)
        action.setShortcut(QtGui.QKeySequence(shortcut))
        # The graph keys are handled contextually by GraphWidget; keeping
        # this scoped avoids clashing with usdview's global shortcuts.
        action.setShortcutContext(QtCore.Qt.WidgetShortcut)
        action.triggered.connect(callback)
        return action

    def AddToggleAction(self, menu, text, checked, callback):
        action = menu.addAction(text)
        action.setCheckable(True)
        action.setChecked(checked)
        action.triggered.connect(lambda *args: callback())
        return action

    def UpdateMenuBar(self):
        menuBar = QtWidgets.QMenuBar(self)
        # On macOS a native menu bar is merged into usdview's global one.
        menuBar.setNativeMenuBar(False)

        viewMenu = menuBar.addMenu("View")
        if self.historyStack:
            a = viewMenu.addAction("Back to Parent")
            a.triggered.connect(self.BackToParentNodeGraph)
            viewMenu.addSeparator()

        self.AddViewAction(
            viewMenu, "Frame Selected", "F", self.graphWidget.FrameSelected
        )
        self.AddViewAction(
            viewMenu, "Frame All", "A", self.graphWidget.FrameAll
        )
        self.AddViewAction(
            viewMenu, "Zoom In", "+", self.graphWidget.graphView.ZoomIn
        )
        self.AddViewAction(
            viewMenu, "Zoom Out", "-", self.graphWidget.graphView.ZoomOut
        )
        viewMenu.addSeparator()

        outputMenu = viewMenu.addMenu("Filter Output")

        self.AddToggleAction(
            outputMenu,
            "None",
            self.selectedOutput is None,
            lambda: self.SwitchToOutput(None),
        )
        outputMenu.addSeparator()

        for output in self.nodeGraph.GetOutputs():
            self.AddToggleAction(
                outputMenu,
                output.GetBaseName(),
                output == self.selectedOutput,
                lambda o=output: self.SwitchToOutput(o),
            )

        toolsMenu = menuBar.addMenu("Tools")

        isMaterial = self.nodeGraph.GetPrim().IsA(UsdShade.Material)
        if isMaterial and mtlxSupported and self.selectedOutput is not None:
            outputName = self.selectedOutput.GetBaseName()

            if outputName == "mtlx:surface":
                a = toolsMenu.addAction("Bake to Texture...")
                a.triggered.connect(self.ShowBakeMtlxDialog)

        exportAction = toolsMenu.addAction("Export as Image...")
        exportAction.triggered.connect(self.ShowExportAsImageDialog)

        toolsMenu.addSeparator()
        preferencesAction = toolsMenu.addAction("Preferences...")
        preferencesAction.triggered.connect(self.ShowPreferencesDialog)

        self.contentLayout.setMenuBar(menuBar)

    def BackToParentNodeGraph(self):
        self.nodeGraph, self.selectedOutput = self.historyStack.pop()
        self.UpdateContentForOutput()

    def SwitchToOutput(self, output):
        if output == self.selectedOutput:
            return  # Already showing, don't reset viewport
        self.selectedOutput = output
        self.UpdateContentForOutput()

    def UpdateContentForOutput(self):
        primPath = str(self.nodeGraph.GetPrim().GetPath())
        outputStr = ""
        if self.selectedOutput is not None:
            outputStr = f" ({self.selectedOutput.GetBaseName()})"

        self.setWindowTitle(f"{self.DEFAULT_TITLE}: {primPath}{outputStr}")

        self.graphWidget.PopulateScene(self.nodeGraph, self.selectedOutput)

        self.UpdateMenuBar()
        self.ScheduleFrameAll()

    def GetDefaultOutput(self):
        # For materials, we try to select the 'surface' output. For NGs, none.
        if not self.nodeGraph.GetPrim().IsA(UsdShade.Material):
            return None

        return next(
            (
                output
                for output in self.nodeGraph.GetOutputs()
                if "surface" in output.GetBaseName()
            ),
            None,
        )

    def SetNodeGraph(self, nodeGraph):
        # Store old NGs on a stack so that we can navigate back using the menu
        if self.nodeGraph is not None and nodeGraph != self.nodeGraph:
            self.historyStack.append((self.nodeGraph, self.selectedOutput))

        self.nodeGraph = nodeGraph
        self.selectedOutput = self.GetDefaultOutput()

        self.placeholderLabel.hide()
        self.graphWidget.show()

        self.UpdateContentForOutput()

    def ScheduleFrameAll(self):
        self.frameRequestId += 1
        requestId = self.frameRequestId
        QtCore.QTimer.singleShot(0, lambda: self.FrameAllOnIdle(requestId))

    def FrameAllOnIdle(self, requestId):
        if requestId != self.frameRequestId:
            return

        self.graphWidget.FrameAll()

    def __init__(self, mainWindow):
        super().__init__(self.DEFAULT_TITLE, mainWindow)

        self.setObjectName(self.DOCK_OBJECT_NAME)
        self.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
        self.setFeatures(
            QtWidgets.QDockWidget.DockWidgetClosable
            | QtWidgets.QDockWidget.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFloatable
        )

        contentWidget = QtWidgets.QWidget(self)
        self.contentLayout = QtWidgets.QVBoxLayout(contentWidget)
        self.contentLayout.setContentsMargins(0, 0, 0, 0)

        self.placeholderLabel = QtWidgets.QLabel(
            "Right-click a Material or NodeGraph prim and choose "
            '"Show Node Graph".',
            contentWidget,
        )
        self.placeholderLabel.setAlignment(QtCore.Qt.AlignCenter)
        self.contentLayout.addWidget(self.placeholderLabel, 1)

        self.graphWidget = GraphWidget(self.SetNodeGraph, self)
        self.contentLayout.addWidget(self.graphWidget, 1)
        self.setWidget(contentWidget)
        self.graphWidget.hide()

        self.nodeGraph = None
        self.historyStack = []  # push (ng, output) when we traverse into child NG
        self.frameRequestId = 0
        self.showNodeGraphShortcut = DEFAULT_SHOW_NODE_GRAPH_SHORTCUT

        self.resize(800, 600)  # set default size

    def ShowNodeGraph(self, nodeGraph):
        if nodeGraph != self.nodeGraph:
            self.SetNodeGraph(nodeGraph)
        self.show()
        self.raise_()

        # On Windows there's a bug where the scroll bars initially don't show.
        if platform.system() == "Windows":
            QtCore.QTimer.singleShot(0, self.ForceInitialResize)

    def ForceInitialResize(self):
        size = self.size()
        self.resize(size.width() + 1, size.height())
        self.resize(size)


class UsdShadeViewDockState(StateSource):
    """Persists the node graph dock layout and preferences."""

    def __init__(self, settings, mainWindow, dockWidget):
        super().__init__(settings, "usdshadeview")

        self._mainWindow = mainWindow
        self._dockWidget = dockWidget

        self.dockState = self.stateProperty("dockState", default="")
        self.dockVisible = self.stateProperty("dockVisible", default=False)
        self.fitViewMargin = self.stateProperty(
            "fitViewMargin",
            default=DEFAULT_FIT_VIEW_MARGIN,
            validator=lambda value: value >= 0,
        )
        self.nodeVerticalSpacing = self.stateProperty(
            "nodeVerticalSpacing",
            default=DEFAULT_NODE_VERTICAL_SPACING,
            validator=lambda value: value >= 0,
        )
        self.graphColors = self.stateProperty(
            "graphColors",
            default=GraphColors().ToDict(),
            propType=dict,
            validator=lambda value: isinstance(value, dict),
        )
        self.hideScrollbars = self.stateProperty(
            "hideScrollbars", default=False
        )
        self.showAllOutputPorts = self.stateProperty(
            "showAllOutputPorts", default=False
        )
        self.showNodeGraphShortcut = self.stateProperty(
            "showNodeGraphShortcut",
            default=DEFAULT_SHOW_NODE_GRAPH_SHORTCUT,
        )

    def Restore(self):
        dockWidget = self._dockWidget
        graphWidget = dockWidget.graphWidget
        graphView = graphWidget.graphView

        # Show a restored floating dock without activating it: otherwise its
        # window becomes key and usdview's menu bar is replaced (macOS).
        dockWidget.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        try:
            if self.dockState:
                state = QtCore.QByteArray.fromBase64(
                    self.dockState.encode("ascii")
                )
                if not self._mainWindow.restoreState(state):
                    print(
                        "WARNING: failed to restore usdshadeview dock state",
                        file=sys.stderr,
                    )

            graphView.SetFitViewMargin(self.fitViewMargin)
            graphWidget.SetNodeVerticalSpacing(self.nodeVerticalSpacing)
            graphWidget.SetColors(GraphColors.FromDict(self.graphColors))
            graphView.SetHideScrollbars(self.hideScrollbars)
            graphWidget.SetShowAllOutputPorts(self.showAllOutputPorts)
            dockWidget.SetShowNodeGraphShortcut(self.showNodeGraphShortcut)
            dockWidget.setVisible(self.dockVisible)
        finally:
            dockWidget.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, False)

    def onSaveState(self, state):
        graphWidget = self._dockWidget.graphWidget
        graphView = graphWidget.graphView

        state["dockState"] = base64.b64encode(
            self._mainWindow.saveState().data()
        ).decode("ascii")
        state["dockVisible"] = self._dockWidget.isVisible()
        state["fitViewMargin"] = graphView.GetFitViewMargin()
        state["nodeVerticalSpacing"] = graphWidget.GetNodeVerticalSpacing()
        state["graphColors"] = graphWidget.GetColors().ToDict()
        state["hideScrollbars"] = graphView.GetHideScrollbars()
        state["showAllOutputPorts"] = graphWidget.GetShowAllOutputPorts()
        state["showNodeGraphShortcut"] = (
            self._dockWidget.GetShowNodeGraphShortcut()
        )
