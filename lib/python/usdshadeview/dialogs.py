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

"""Standalone dialogs used by the plugin."""

import os

from pxr import Sdr, Usd
from pxr.Usdviewq.qt import QtCore, QtGui, QtWidgets
from pxr.Usdviewq.scalarTypes import ToString

from .compat import PySideModule, UsdBakeMtlx
from .constants import GraphColors, NodeType


class BakeMtlxDialog(QtWidgets.QDialog):
    def __init__(self, material, parent=None):
        super().__init__(parent)
        self.material = material

        self.setWindowTitle("Bake to Texture")

        mainLayout = QtWidgets.QVBoxLayout()
        formLayout = QtWidgets.QFormLayout()

        self.dirPath = os.getcwd()
        self.dirBrowseButton = QtWidgets.QPushButton("Open...")
        self.dirBrowseButton.clicked.connect(self.OpenDirDialog)
        formLayout.addRow("Directory:", self.dirBrowseButton)

        self.imgWidth = QtWidgets.QSpinBox()
        self.imgWidth.setRange(1, 4096)
        self.imgWidth.setValue(1024)
        formLayout.addRow("Image Width:", self.imgWidth)

        self.imgHeight = QtWidgets.QSpinBox()
        self.imgHeight.setRange(1, 4096)
        self.imgHeight.setValue(1024)
        formLayout.addRow("Image Height:", self.imgHeight)

        self.imgHdr = QtWidgets.QCheckBox()
        formLayout.addRow("HDR:", self.imgHdr)

        self.imgAverage = QtWidgets.QCheckBox()
        formLayout.addRow("Average Images:", self.imgAverage)

        mainLayout.addLayout(formLayout)

        self.buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        self.buttonBox.accepted.connect(self.OnAccept)
        self.buttonBox.rejected.connect(self.reject)
        mainLayout.addWidget(self.buttonBox)

        self.setLayout(mainLayout)

        # disable resizing
        self.setFixedWidth(self.sizeHint().width())
        self.setFixedHeight(self.sizeHint().height())

    def OpenDirDialog(self):
        dirPath = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Select Directory"
        )
        if dirPath:
            self.dirPath = dirPath

    def OnAccept(self):
        UsdBakeMtlx.BakeMaterial(
            self.material,
            self.dirPath,
            self.imgWidth.value(),
            self.imgHeight.value(),
            self.imgHdr.isChecked(),
            self.imgAverage.isChecked(),
        )

        self.accept()  # close dialog


# Global dict <NodeInput, DialogWindow>, which we use to keep alive,
# deduplicate and bring to front existing metadata dialogs.
metadataDialogs = {}


class MetadataDialog(QtWidgets.QDialog):
    def MakeDataBacking(self, metadata):
        data = []
        for key, value in sorted(metadata.items()):
            data.append([str(key), ToString(value)])
        return data

    class TableModel(QtCore.QAbstractTableModel):
        def __init__(self, data=[{}], parent=None):
            super().__init__(parent)
            self._data = data

        def headerData(self, section, orientation, role):
            headers = ["Name", "Value"]
            if role == QtCore.Qt.DisplayRole:
                if orientation == QtCore.Qt.Horizontal:
                    return headers[section]
            return None

        def columnCount(self, _):
            return 2

        def rowCount(self, _):
            return len(self._data)

        # TODO: we could show the type in the tooltip
        def data(self, index, role):
            column = index.column()
            if role == QtCore.Qt.DisplayRole:
                row = index.row()
                return self._data[row][column]
            return None

    def MakeTableViewFromData(self, data):
        tableModel = self.TableModel(data)
        table = QtWidgets.QTableView()
        table.setModel(tableModel)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch
        )
        table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        table.setWordWrap(False)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.setFrameShape(QtWidgets.QFrame.NoFrame)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        return table

    def __init__(self, metadata, parent=None):
        super().__init__(parent)

        data = self.MakeDataBacking(metadata)
        table = self.MakeTableViewFromData(data)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(table)
        self.setLayout(layout)

        self.setWindowTitle("Input Metadata")
        # fixed size to remove 'maximize' button
        self.setFixedWidth(self.sizeHint().width() * 1.75)
        self.setFixedHeight(self.sizeHint().height())


def OpenMetadataDialog(nodeInput, metadata, parent=None):
    if nodeInput in metadataDialogs:
        d = metadataDialogs[nodeInput]
        if d.isVisible():  # check if window was closed
            if parent is None or d.parentWidget() is parent:
                d.raise_()
                d.activateWindow()
                return
            d.close()
        d.deleteLater()
        metadataDialogs.pop(nodeInput, None)

    d = MetadataDialog(metadata, parent)
    metadataDialogs[nodeInput] = d
    d.show()


# Global dict <NodeDef ID, DialogWindow>, which we use to keep alive,
# deduplicate and bring to front existing NodeDef dialogs.
nodeDefDialogs = {}


class NodeDefDialog(QtWidgets.QDialog):
    def MakeDataBacking(self, nodeDef, portNames, portGetter):
        portNames.sort()
        data = []
        for name in portNames:
            i = portGetter(name)

            if Usd.GetVersion() > (0, 24, 8):
                typeStr = str(i.GetTypeAsSdfType().GetSdfType())
            else:
                typeStr = str(i.GetTypeAsSdfType()[0])

            entry = [name, typeStr, ToString(i.GetDefaultValue()), i.GetHelp()]
            data.append(entry)
        return data

    class TableModel(QtCore.QAbstractTableModel):
        def __init__(self, data=[{}], parent=None):
            super().__init__(parent)
            self._data = data

        def headerData(self, section, orientation, role):
            headers = ["Name", "Type", "Default", "Documentation"]
            if role == QtCore.Qt.DisplayRole:
                if orientation == QtCore.Qt.Horizontal:
                    return headers[section]
            return None

        def columnCount(self, _):
            return 4

        def rowCount(self, _):
            return len(self._data)

        def data(self, index, role):
            column = index.column()
            if role == QtCore.Qt.DisplayRole or (
                role == QtCore.Qt.ToolTipRole and column >= 2
            ):
                row = index.row()
                return self._data[row][column]
            return None

    def MakeTableViewFromData(self, data):
        tableModel = self.TableModel(data)
        table = QtWidgets.QTableView()
        table.setModel(tableModel)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch
        )
        table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        table.setWordWrap(False)
        table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        table.setFrameShape(QtWidgets.QFrame.NoFrame)
        table.setAlternatingRowColors(True)
        table.setShowGrid(False)
        return table

    def __init__(self, nodeDef, parent=None):
        super().__init__(parent)

        name = nodeDef.GetIdentifier()
        family = nodeDef.GetFamily()
        doc = nodeDef.GetHelp()

        layout = QtWidgets.QVBoxLayout()
        if family != "":
            layout.addWidget(QtWidgets.QLabel(f"Family: {family}"))

        # NOTE: Sdr documentation is not filled in for UsdPreviewSurface nodes (OpenUSD issue #3230)
        if doc != "":
            label = QtWidgets.QLabel(f"Documentation: {doc}")
            label.setWordWrap(True)
            layout.addWidget(label)

        if Usd.GetVersion() >= (0, 25, 5):
            shaderInputNames = nodeDef.GetShaderInputNames()
            shaderOutputNames = nodeDef.GetShaderOutputNames()
            shaderInput = nodeDef.GetShaderInput
            shaderOutput = nodeDef.GetShaderOutput
        else:
            shaderInputNames = nodeDef.GetInputNames()
            shaderOutputNames = nodeDef.GetOutputNames()
            shaderInput = nodeDef.GetInput
            shaderOutput = nodeDef.GetOutput

        inputData = self.MakeDataBacking(
            nodeDef, shaderInputNames, shaderInput
        )
        inputTable = self.MakeTableViewFromData(inputData)

        outputData = self.MakeDataBacking(
            nodeDef, shaderOutputNames, shaderOutput
        )
        outputTable = self.MakeTableViewFromData(outputData)

        # almost always there are fewer outputs. adaptive table size removes whitespace.
        outputTable.setMaximumHeight(outputTable.size().height() / 2)
        outputTable.setSizeAdjustPolicy(
            QtWidgets.QAbstractScrollArea.AdjustToContents
        )

        if len(inputData) + len(outputData) > 0:
            tabs = QtWidgets.QTabWidget()
            if len(inputData) > 0:
                tabs.addTab(inputTable, "Inputs")
            if len(outputData) > 0:
                tabs.addTab(outputTable, "Outputs")
            layout.addWidget(tabs)

        self.setLayout(layout)
        self.setWindowTitle(name)
        # fixed size to remove 'maximize' button
        self.setFixedWidth(self.sizeHint().width())
        self.setFixedHeight(self.sizeHint().height())


def OpenNodeDefDialog(ndId, parent=None):
    if ndId in nodeDefDialogs:
        d = nodeDefDialogs[ndId]
        if d.isVisible():  # check if window was closed
            if parent is None or d.parentWidget() is parent:
                d.raise_()
                d.activateWindow()
                return
            d.close()
        d.deleteLater()
        nodeDefDialogs.pop(ndId, None)

    reg = Sdr.Registry()
    nd = reg.GetShaderNodeByIdentifier(ndId)
    if nd is not None:
        d = NodeDefDialog(nd, parent)
        nodeDefDialogs[ndId] = d
        d.show()


NODE_COLOR_LABELS = [
    (NodeType.USDA, "USDA node color:"),
    (NodeType.MDL, "MDL node color:"),
    (NodeType.MTLX, "MaterialX node color:"),
    (NodeType.OSL, "OSL node color:"),
    (NodeType.NODE_GRAPH, "Node graph color:"),
    (NodeType.UNKNOWN, "Unknown node color:"),
]


class ColorButton(QtWidgets.QPushButton):
    """A button showing a color swatch and opening a color picker."""

    def __init__(self, color, parent=None):
        super().__init__(parent)
        self.color = QtGui.QColor(color)
        self.setFixedWidth(110)
        self.setToolTip("Click to choose a color.")
        self.clicked.connect(self.PickColor)
        self.UpdateSwatch()

    def GetColor(self):
        return self.color.name()

    def SetColor(self, color):
        self.color = QtGui.QColor(color)
        self.UpdateSwatch()

    def UpdateSwatch(self):
        color = self.color
        luminance = (
            0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
        ) / 255.0
        textColor = "#000" if luminance > 0.5 else "#fff"
        self.setText(color.name())
        self.setStyleSheet(
            f"QPushButton {{ background-color: {color.name()}; "
            f"color: {textColor}; border: 1px solid #000; "
            "padding: 2px 4px; }"
        )

    def PickColor(self):
        color = QtWidgets.QColorDialog.getColor(
            self.color, self, "Select Color"
        )
        if color.isValid():
            self.SetColor(color)


class PreferencesDialog(QtWidgets.QDialog):
    def __init__(
        self,
        parent,
        fitViewMargin,
        nodeVerticalSpacing,
        hideScrollbars,
        showAllOutputPorts,
        showNodeGraphShortcut,
        colors,
    ):
        super().__init__(parent)

        self.setWindowTitle("Preferences")

        formLayout = QtWidgets.QFormLayout()

        self.showNodeGraphShortcut = QtWidgets.QKeySequenceEdit(
            QtGui.QKeySequence(showNodeGraphShortcut)
        )
        self.showNodeGraphShortcut.setToolTip(
            'Keyboard shortcut for the "Show Node Graph" context menu action.'
        )
        formLayout.addRow(
            "Show Node Graph shortcut:", self.showNodeGraphShortcut
        )

        self.fitViewMargin = QtWidgets.QSpinBox()
        self.fitViewMargin.setRange(0, 200)
        self.fitViewMargin.setSingleStep(5)
        self.fitViewMargin.setValue(fitViewMargin)
        self.fitViewMargin.setSuffix(" px")
        self.fitViewMargin.setToolTip(
            "Margin added around the nodes when framing the graph."
        )
        formLayout.addRow("Fit view margin:", self.fitViewMargin)

        self.nodeVerticalSpacing = QtWidgets.QSpinBox()
        self.nodeVerticalSpacing.setRange(0, 200)
        self.nodeVerticalSpacing.setSingleStep(1)
        self.nodeVerticalSpacing.setValue(nodeVerticalSpacing)
        self.nodeVerticalSpacing.setSuffix(" px")
        self.nodeVerticalSpacing.setToolTip(
            "Vertical gap between the nodes in each graph column."
        )
        formLayout.addRow("Node vertical spacing:", self.nodeVerticalSpacing)

        self.hideScrollbars = QtWidgets.QCheckBox("Hide scrollbars")
        self.hideScrollbars.setChecked(hideScrollbars)
        self.hideScrollbars.setToolTip(
            "Hide the scrollbars around the node graph view."
        )

        self.showAllOutputPorts = QtWidgets.QCheckBox("Show all output ports")
        self.showAllOutputPorts.setChecked(showAllOutputPorts)
        self.showAllOutputPorts.setToolTip(
            "Show output rows on nodes even for single ports with "
            "default names such as 'out' or 'result'."
        )

        colorsGroup = QtWidgets.QGroupBox("Colors")
        colorsLayout = QtWidgets.QFormLayout(colorsGroup)

        self.nodeColorButtons = {}
        for nodeType, label in NODE_COLOR_LABELS:
            button = ColorButton(colors.GetNodeColor(nodeType))
            self.nodeColorButtons[nodeType.name] = button
            colorsLayout.addRow(label, button)

        self.nodeBackgroundColor = ColorButton(colors.nodeBackgroundColor)
        colorsLayout.addRow("Node background color:", self.nodeBackgroundColor)

        self.connectionColor = ColorButton(colors.connectionColor)
        colorsLayout.addRow("Connection color:", self.connectionColor)

        self.backgroundColor = ColorButton(colors.backgroundColor)
        colorsLayout.addRow("Background color:", self.backgroundColor)

        self.gridColor = ColorButton(colors.gridColor)
        colorsLayout.addRow("Background grid color:", self.gridColor)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(formLayout)
        layout.addWidget(colorsGroup)
        layout.addWidget(self.hideScrollbars)
        layout.addWidget(self.showAllOutputPorts)

        buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttonBox.accepted.connect(self.accept)
        buttonBox.rejected.connect(self.reject)
        layout.addWidget(buttonBox)

        self.setLayout(layout)
        self.setFixedWidth(self.sizeHint().width() * 1.5)

    def GetFitViewMargin(self):
        return self.fitViewMargin.value()

    def GetNodeVerticalSpacing(self):
        return self.nodeVerticalSpacing.value()

    def GetColors(self):
        return GraphColors(
            nodeColors={
                key: button.GetColor()
                for key, button in self.nodeColorButtons.items()
            },
            connectionColor=self.connectionColor.GetColor(),
            backgroundColor=self.backgroundColor.GetColor(),
            gridColor=self.gridColor.GetColor(),
            nodeBackgroundColor=self.nodeBackgroundColor.GetColor(),
        )

    def GetHideScrollbars(self):
        return self.hideScrollbars.isChecked()

    def GetShowAllOutputPorts(self):
        return self.showAllOutputPorts.isChecked()

    def GetShowNodeGraphShortcut(self):
        return self.showNodeGraphShortcut.keySequence().toString(
            QtGui.QKeySequence.PortableText
        )

    def Run(self):
        if PySideModule == "PySide6":
            return self.exec()
        return self.exec_()


class ValueArrayDialog(QtWidgets.QDialog):
    def __init__(self, values, parent=None):
        super().__init__(parent)

        self.setWindowTitle("Array Values")

        listEntries = []
        for v in values:
            listEntries.append(ToString(v))

        self.listWidget = QtWidgets.QListWidget()
        self.listWidget.addItems(listEntries)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(self.listWidget)
        self.setLayout(layout)

        # fixed size to remove 'maximize' button
        self.setFixedWidth(self.sizeHint().width() * 1.75)
        self.setFixedHeight(self.sizeHint().height())


def ShowValueArrayDialog(value, parent=None):
    d = ValueArrayDialog(value, parent)
    try:
        if PySideModule == "PySide6":
            d.exec()
        else:
            d.exec_()
    finally:
        d.deleteLater()
