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
from pxr.Usdviewq.qt import QtCore, QtWidgets
from pxr.Usdviewq.scalarTypes import ToString

from .compat import PySideModule, UsdBakeMtlx


class BakeMtlxDialog(QtWidgets.QDialog):
    def __init__(self, material):
        super().__init__()
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

    def __init__(self, metadata):
        super().__init__()

        data = self.MakeDataBacking(metadata)
        table = self.MakeTableViewFromData(data)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(table)
        self.setLayout(layout)

        self.setWindowTitle("Input Metadata")
        # fixed size to remove 'maximize' button
        self.setFixedWidth(self.sizeHint().width() * 1.75)
        self.setFixedHeight(self.sizeHint().height())


def OpenMetadataDialog(nodeInput, metadata):
    if nodeInput in metadataDialogs:
        d = metadataDialogs[nodeInput]
        if d.isVisible():  # check if window was closed
            d.raise_()
            d.activateWindow()
            return

    d = MetadataDialog(metadata)
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

    def __init__(self, nodeDef):
        super().__init__()

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
        self.setFixedWidth(self.size().width())
        self.setFixedHeight(self.sizeHint().height())


def OpenNodeDefDialog(ndId):
    if ndId in nodeDefDialogs:
        d = nodeDefDialogs[ndId]
        if d.isVisible():  # check if window was closed
            d.raise_()
            d.activateWindow()
            return

    reg = Sdr.Registry()
    nd = reg.GetShaderNodeByIdentifier(ndId)
    if nd is not None:
        d = NodeDefDialog(nd)
        nodeDefDialogs[ndId] = d
        d.show()


class PreferencesDialog(QtWidgets.QDialog):
    def __init__(self, parent, fitViewMargin, hideScrollbars):
        super().__init__(parent)

        self.setWindowTitle("Preferences")

        formLayout = QtWidgets.QFormLayout()

        self.fitViewMargin = QtWidgets.QDoubleSpinBox()
        self.fitViewMargin.setRange(0.0, 200.0)
        self.fitViewMargin.setDecimals(1)
        self.fitViewMargin.setSingleStep(5.0)
        self.fitViewMargin.setValue(fitViewMargin)
        self.fitViewMargin.setSuffix(" px")
        self.fitViewMargin.setToolTip(
            "Margin added around the nodes when framing the graph."
        )
        formLayout.addRow("Fit view margin:", self.fitViewMargin)

        self.hideScrollbars = QtWidgets.QCheckBox("Hide scrollbars")
        self.hideScrollbars.setChecked(hideScrollbars)
        self.hideScrollbars.setToolTip(
            "Hide the scrollbars around the node graph view."
        )

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(formLayout)
        layout.addWidget(self.hideScrollbars)

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

    def GetHideScrollbars(self):
        return self.hideScrollbars.isChecked()

    def Run(self):
        if PySideModule == "PySide6":
            return self.exec()
        return self.exec_()


class ValueArrayDialog(QtWidgets.QDialog):
    def __init__(self, values):
        super().__init__()

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


def ShowValueArrayDialog(value):
    d = ValueArrayDialog(value)
    if PySideModule == "PySide6":
        d.exec()
    else:
        d.exec_()
