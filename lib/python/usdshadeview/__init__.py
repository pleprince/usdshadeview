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

"""Visualize UsdShade node graphs in a usdview panel."""

import platform

from pxr import Sdr, Tf, Usd
from pxr.Usdviewq.plugin import PluginContainer
from pxr.Usdviewq.primContextMenu import PrimContextMenu
from pxr.Usdviewq.qt import QtCore

# Re-exported so existing imports of the plugin module keep working.
from .compat import (
    PySideModule,
    UsdBakeMtlx,
    enableHwAcceleration,
    mtlxSupported,
    oiio,
    oiioSupported,
)
from .connections import ConnectionWidget, SplineConnectionWidget
from .constants import (
    ARRAY_BUTTON_STYLE,
    AUX_BUTTON_STYLE,
    BORDER_WIDGET_STYLE,
    DEFAULT_FIT_VIEW_MARGIN,
    MAX_NODE_GRAPH_DEPTH,
    SELECTED_NODE_STYLE,
    NodeColors,
    NodeType,
    PortType,
    UIColors,
)
from .context_menu import ShowUsdShadeGraphContextMenuItem
from .dialogs import (
    BakeMtlxDialog,
    MetadataDialog,
    NodeDefDialog,
    OpenMetadataDialog,
    OpenNodeDefDialog,
    PreferencesDialog,
    ShowValueArrayDialog,
    ValueArrayDialog,
    metadataDialogs,
    nodeDefDialogs,
)
from .dock import GraphDockWidget, UsdShadeViewDockState
from .graph import GraphView, GraphWidget
from .nodes import (
    GraphNode,
    MakeNgInputNode,
    MakeNgOutputNode,
    MakeSdrShaderNode,
    ShaderNode,
)
from .utils import (
    FormatFloatShort,
    GetShaderNodeType,
    IsDefaultOutputPortName,
    IsOpenFileInFolderSupported,
    IsOpenFileWithSystemSupported,
    OpenFileInFolderWithSystem,
    OpenFileWithSystem,
)
from .value_widgets import (
    AlphaWidget,
    MakeArrayValueWidget,
    MakeAssetValueWidget,
    MakeColorValueWidget,
    MakeMatrixValueWidget,
    MakePortRowWidget,
    MakePortWidget,
    MakePropertyWidget,
    MakeValueProxyWidget,
    MakeValueStr,
    MakeValueWidget,
    MakeVectorValueWidget,
    PixmapToBase64,
    ValueProxyWidget,
)


class UsdShadeViewContainer(PluginContainer):
    SDR_NODES_COMMAND_NS = "UsdShadeView.SdrNodes"
    TOGGLE_DOCK_COMMAND_NS = "UsdShadeView.ToggleDock"

    def registerPlugins(self, plugRegistry, usdviewApi):
        self.usdviewApi = usdviewApi
        self.dockWidget = None
        self.sdrNodesMenu = plugRegistry.registerCommandPlugin(
            self.SDR_NODES_COMMAND_NS, "List of Sdr nodes", lambda *args: None
        )
        self.toggleDockCommand = plugRegistry.registerCommandPlugin(
            self.TOGGLE_DOCK_COMMAND_NS,
            "UsdShade Node Graph",
            lambda *args: self.ToggleDock(),
            "Show or hide the UsdShade node graph panel.",
        )

    def configureView(self, plugRegistry, plugUIBuilder):
        windowMenu = plugUIBuilder.findOrCreateMenu("Window")
        sdrNodeMenu = windowMenu.findOrCreateSubmenu("Sdr Nodes")

        reg = Sdr.Registry()

        if Usd.GetVersion() >= (0, 25, 5):
            ndIds = reg.GetShaderNodeIdentifiers()
        else:
            ndIds = reg.GetNodeIdentifiers()

        ndIds.sort()
        for ndId in ndIds:
            nd = reg.GetShaderNodeByIdentifier(ndId)
            if nd is not None:
                item = plugRegistry.registerCommandPlugin(
                    f"{self.SDR_NODES_COMMAND_NS}.{ndId}",
                    ndId,
                    lambda *args, n=ndId: OpenNodeDefDialog(n),
                )
                sdrNodeMenu.addItem(item)

        self.CreateDockWidget(windowMenu)
        self.hijackPrimContextMenu()

    def CreateDockWidget(self, windowMenu):
        mainWindow = self.usdviewApi.qMainWindow

        self.dockWidget = GraphDockWidget(mainWindow)
        mainWindow.addDockWidget(
            QtCore.Qt.RightDockWidgetArea, self.dockWidget
        )

        dockAction = windowMenu.addItem(self.toggleDockCommand)
        dockAction.setCheckable(True)
        dockAction.setChecked(self.dockWidget.isVisible())
        self.dockWidget.visibilityChanged.connect(dockAction.setChecked)

        dockState = UsdShadeViewDockState(
            self.GetSettingsSource(), mainWindow, self.dockWidget
        )
        dockState.Restore()

    def GetSettingsSource(self):
        getSettings = getattr(self.usdviewApi, "GetSettings", None)
        if getSettings is not None:
            return getSettings()
        # Older usdview versions have no public accessor; the view
        # settings are themselves a child state source of the settings.
        return self.usdviewApi.dataModel.viewSettings

    def ToggleDock(self):
        if self.dockWidget.isVisible():
            self.dockWidget.hide()
        else:
            self.dockWidget.show()
            self.dockWidget.raise_()

    def ShowNodeGraph(self, nodeGraph):
        self.dockWidget.ShowNodeGraph(nodeGraph)

    def hijackPrimContextMenu(self):
        usdviewApi = self.usdviewApi
        viewContainer = self

        oldInitMethod = PrimContextMenu.__init__

        def trampolineInitMethod(self, parent, item, appController):
            oldInitMethod(self, parent, item, appController)

            if not item:
                return

            menuItem = ShowUsdShadeGraphContextMenuItem(
                appController, item, usdviewApi, viewContainer
            )

            action = self.addAction(menuItem.GetText())
            action.setEnabled(menuItem.IsEnabled())
            action.triggered.connect(lambda value: menuItem.RunCommand())

        PrimContextMenu.__init__ = trampolineInitMethod


Tf.Type.Define(UsdShadeViewContainer)


# Ignore warning spam in certain configurations
baseHandler = QtCore.qInstallMessageHandler(None)


def customMessageHandler(mode, context, message):
    if "unsupported paint engine type" in message:
        return
    if baseHandler is not None:
        baseHandler(mode, context, message)


if enableHwAcceleration and platform.system() == "Darwin":
    QtCore.qInstallMessageHandler(customMessageHandler)
