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

import os, sys, platform, subprocess, base64, shutil
from enum import Enum

from pxr import Tf, Usd, UsdShade, Sdr, Sdf, Gf, Ar
from pxr.Usdviewq.plugin import PluginContainer
from pxr.Usdviewq.primContextMenuItems import PrimContextMenuItem
from pxr.Usdviewq.primContextMenu import PrimContextMenu
from pxr.Usdviewq.qt import QtCore, QtGui, QtWidgets, QGLWidget, QGLFormat, GetPySideModule
from pxr.Usdviewq.scalarTypes import ToClipboard, ToString
from pxr.Usdviewq.settings import StateSource

PySideModule = GetPySideModule()

if PySideModule == 'PySide2':
    # There is an issue on Windows where under certain circumstances the buttons in the QGraphicsView
    # can not be clicked anymore. There's also some error log spam. This might not affect all OSes.
    enableHwAcceleration = False
else:
    # Disable this if you run into rendering issues
    enableHwAcceleration = os.getenv("USDSHADEVIEW_HW_ACCEL", "1") in ("1", "true", "yes", "on")

# Abortion criterium for circular node graphs
MAX_NODE_GRAPH_DEPTH = 80

mtlxSupported = True
try:
    from pxr import UsdBakeMtlx
except ModuleNotFoundError:
    mtlxSupported = False

# Allows us to support EXR and other image file types that Qt doesn't
oiioSupported = True
try:
    import OpenImageIO as oiio
    oiioSupported = hasattr(oiio, 'ImageInput') # Guard against broken installation
except ModuleNotFoundError:
    oiioSupported = False

class UIColors(str, Enum):
    GOLD = "#c39a46"
    CHARCOAL = "#373737" # usdviewstyle.qss QTable background
    MDL_GREEN = "#77AB47"
    DARK_GREY = "#2a2a2a" # match usdviewstyle.qss
    LIGHT_RED = "#e68483"
    LIGHT_BLUE = "#bec8f4"
    LIGHT_PURPLE = "#c8a7f7"
    LIGHT_GREY = "#aaaaaa"

class NodeType(Enum):
    MDL = 1 # TODO: maybe we can promote MDL to some general 'source asset' type node?
    MTLX = 2
    OSL = 3
    USDA = 4
    NODE_GRAPH = 5
    PARENT_INPUTS = 6
    PARENT_OUTPUTS = 7
    UNKNOWN = 8

NodeColors = {
    NodeType.USDA: UIColors.GOLD,
    NodeType.MDL: UIColors.MDL_GREEN,
    NodeType.MTLX: UIColors.LIGHT_RED,
    NodeType.OSL: UIColors.LIGHT_BLUE,
    NodeType.NODE_GRAPH: UIColors.LIGHT_PURPLE,
    NodeType.PARENT_INPUTS: UIColors.LIGHT_PURPLE,
    NodeType.PARENT_OUTPUTS: UIColors.LIGHT_PURPLE,
    NodeType.UNKNOWN: UIColors.LIGHT_GREY
}

BORDER_WIDGET_STYLE = f"""
    QWidget#ThisWidget {{
        background-color: {UIColors.CHARCOAL.value};
        border-color: #000;
        border-width: 1px;
        border-style: inset;
    }}
"""

SELECTED_NODE_STYLE = f"""
    QWidget#ThisWidget {{
        background-color: #454545;
        border-color: {UIColors.GOLD.value};
        border-width: 1px;
        border-style: solid;
    }}
"""

AUX_BUTTON_STYLE = """
    QPushButton {
        color: #000;
        border-width: 1px;
        background: none;
        border-radius: 0px;
        padding: 2 4 2 4;
        font-size: 10px;
        font-weight: 200;
        font-family: monospace;
    }
    QPushButton:pressed {
        background-color: #11000000;
    }
"""

ARRAY_BUTTON_STYLE = """
    QPushButton {
        color: #fff;
        border-width: 1px;
        background: none;
        border-radius: 0px;
        padding: 2 4 2 4;
        font-size: 10px;
    }
    QPushButton:pressed {
        background-color: #11000000;
    }
"""

class PortType(Enum):
    INPUT = 1
    OUTPUT = 2

def GetShaderNodeType(shaderOrNG):
    if isinstance(shaderOrNG, UsdShade.NodeGraph):
        return NodeType.NODE_GRAPH

    if Usd.GetVersion() >= (0, 24, 5):
        for s in shaderOrNG.GetSourceTypes():
            if s == 'mdl':
                return NodeType.MDL

    ndId = shaderOrNG.GetShaderId()
    if not ndId:
        return NodeType.UNKNOWN

    sdrReg = Sdr.Registry()
    nd = sdrReg.GetShaderNodeByIdentifier(ndId)
    if not nd:
        return NodeType.UNKNOWN # Can be a mtlx ND mismatch

    context = nd.GetContext()
    if not context:
        return NodeType.UNKNOWN

    if context == 'usda':
        return NodeType.USDA
    elif nd.GetSourceType() == 'mtlx':
        return NodeType.MTLX
    elif nd.GetSourceType() == 'osl':
        return NodeType.OSL

    return NodeType.UNKNOWN

def IsDefaultOutputPortName(name):
    return name == 'out' or name == 'result'

def IsOpenFileWithSystemSupported():
    return platform.system() in ['Windows', 'Darwin'] or shutil.which("xdg-open")

def OpenFileWithSystem(filePath):
    if platform.system() == 'Darwin':
        os.system(f'open {filePath}')
    elif platform.system() == 'Windows':
        os.system(f'start {filePath}')
    else:
        subprocess.call(('xdg-open', filePath))

def IsOpenFileInFolderSupported():
    return platform.system() in ['Windows', 'Darwin']

def OpenFileInFolderWithSystem(filePath):
    if platform.system() == 'Darwin':
        os.system(f'open -R {filePath}')
    elif platform.system() == 'Windows':
        os.system(f'explorer.exe /select,{filePath}')

def FormatFloatShort(value, numDigits = 4):
    if abs(value) < 1e-5:
        return "0"
    if abs(value) < 1e-3:
        return f"{value:.2e}"
    else:
        s = f"{value:.{numDigits}f}"
        s = s.rstrip('0')
        if s.endswith('.'):
            s += '0'
        return s

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

        self.buttonBox = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        self.buttonBox.accepted.connect(self.OnAccept)
        self.buttonBox.rejected.connect(self.reject)
        mainLayout.addWidget(self.buttonBox)

        self.setLayout(mainLayout)

        # disable resizing
        self.setFixedWidth(self.sizeHint().width())
        self.setFixedHeight(self.sizeHint().height())

    def OpenDirDialog(self):
        dirPath = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Directory")
        if dirPath:
            self.dirPath = dirPath

    def OnAccept(self):
        UsdBakeMtlx.BakeMaterial(
            self.material, self.dirPath,
            self.imgWidth.value(), self.imgHeight.value(),
            self.imgHdr.isChecked(), self.imgAverage.isChecked())

        self.accept() # close dialog


# Global dict <NodeInput, DialogWindow>, which we use to keep alive,
# deduplicate and bring to front existing metadata dialogs.
metadataDialogs = {}

class MetadataDialog(QtWidgets.QDialog):

    def MakeDataBacking(self, metadata):
        data = []
        for key, value in sorted(metadata.items()):
            data.append([ str(key), ToString(value) ])
        return data

    class TableModel(QtCore.QAbstractTableModel):
        def __init__(self, data=[{}], parent=None):
            super().__init__(parent)
            self._data = data

        def headerData(self, section, orientation, role):
            headers = [ 'Name', 'Value' ]
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
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
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

        self.setWindowTitle('Input Metadata')
        # fixed size to remove 'maximize' button
        self.setFixedWidth(self.sizeHint().width() * 1.75)
        self.setFixedHeight(self.sizeHint().height())


def OpenMetadataDialog(nodeInput, metadata):
    if nodeInput in metadataDialogs:
        d = metadataDialogs[nodeInput]
        if d.isVisible(): # check if window was closed
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

            entry = [ name, typeStr, ToString(i.GetDefaultValue()), i.GetHelp() ]
            data.append(entry)
        return data

    class TableModel(QtCore.QAbstractTableModel):
        def __init__(self, data=[{}], parent=None):
            super().__init__(parent)
            self._data = data

        def headerData(self, section, orientation, role):
            headers = [ 'Name', 'Type', 'Default', 'Documentation' ]
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
            if role == QtCore.Qt.DisplayRole or (role == QtCore.Qt.ToolTipRole and column >= 2):
                row = index.row()
                return self._data[row][column]
            return None

    def MakeTableViewFromData(self, data):
        tableModel = self.TableModel(data)
        table = QtWidgets.QTableView()
        table.setModel(tableModel)
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
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
        if family != '':
            layout.addWidget(QtWidgets.QLabel(f"Family: {family}"))

        # NOTE: Sdr documentation is not filled in for UsdPreviewSurface nodes (OpenUSD issue #3230)
        if doc != '':
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

        inputData = self.MakeDataBacking(nodeDef, shaderInputNames, shaderInput)
        inputTable = self.MakeTableViewFromData(inputData)

        outputData = self.MakeDataBacking(nodeDef, shaderOutputNames, shaderOutput)
        outputTable = self.MakeTableViewFromData(outputData)

        # almost always there are fewer outputs. adaptive table size removes whitespace.
        outputTable.setMaximumHeight(outputTable.size().height() / 2)
        outputTable.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.AdjustToContents)

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
        if d.isVisible(): # check if window was closed
            d.raise_()
            d.activateWindow()
            return

    reg = Sdr.Registry()
    nd = reg.GetShaderNodeByIdentifier(ndId)
    if nd is not None:
        d = NodeDefDialog(nd)
        nodeDefDialogs[ndId] = d
        d.show()


class GraphNode(QtWidgets.QFrame):

    def __init__(self):
        super().__init__()

        self.selected = False

        nodeLayout = QtWidgets.QVBoxLayout()
        nodeLayout.setContentsMargins(0, 0, 0, 0)
        nodeLayout.setSpacing(0)
        self.setLayout(nodeLayout)

        self.setStyleSheet(BORDER_WIDGET_STYLE)
        self.setObjectName("ThisWidget")

    def SetSelected(self, selected):
        if selected == self.selected:
            return

        self.selected = selected
        self.setStyleSheet(
            SELECTED_NODE_STYLE if selected else BORDER_WIDGET_STYLE)

    def AddHeader(self, title, subtitle, color, auxButtonText = '', auxButtonTooltip = ''):
        nameLabel = QtWidgets.QLabel(title)
        typeLabel = QtWidgets.QLabel(subtitle)
        typeLabel.setStyleSheet("QLabel { font-style: italic; font-weight: 100; }")

        nameTypeLayout = QtWidgets.QVBoxLayout()
        nameTypeLayout.setSpacing(2)
        nameTypeLayout.addWidget(nameLabel)
        nameTypeLayout.addWidget(typeLabel)

        headerLayout = QtWidgets.QHBoxLayout()
        headerLayout.setContentsMargins(4, 4, 4, 4)
        headerLayout.addLayout(nameTypeLayout)
        headerLayout.addStretch()

        if auxButtonText:
            auxButton = QtWidgets.QPushButton(auxButtonText)
            auxButton.setToolTip(auxButtonTooltip)
            auxButton.setStyleSheet(AUX_BUTTON_STYLE)
            auxButton.clicked.connect(self.AuxButtonPressed)
            headerLayout.addWidget(auxButton)

        headerFrame = QtWidgets.QFrame()
        headerFrame.setLayout(headerLayout)
        headerFrame.setStyleSheet(f"QFrame {{ background-color: {color.value}; color: #000; }}")

        self.layout().addWidget(headerFrame)


# Sets up a context menu on a value widget
class ValueProxyWidget(QtWidgets.QWidget):

    def __init__(self, value, nodeInput):
        super().__init__()
        self.value = value
        self.nodeInput = nodeInput
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self.ShowValueContextMenu)

    def ShowValueContextMenu(self, position: QtCore.QPoint):
        menu = QtWidgets.QMenu()

        a1 = menu.addAction("Copy Value")
        a2 = None
        if self.nodeInput:
            attr = self.nodeInput.GetAttr()
            metadata = attr.GetAllMetadata()

            if metadata:
                a2 = menu.addAction("Show Metadata")

        isLocalFile = isinstance(self.value, Sdf.AssetPath) and os.path.exists(self.value.resolvedPath)

        a3 = None
        a4 = None
        if isLocalFile:
            filePath = self.value.resolvedPath

            if IsOpenFileWithSystemSupported():
                a3 = menu.addAction("Open File")

            if IsOpenFileInFolderSupported():
                a4 = menu.addAction("Open File in Folder")

        globalPos = self.mapToGlobal(position)
        if PySideModule == 'PySide6':
            selectedAction = menu.exec(globalPos)
        else:
            selectedAction = menu.exec_(globalPos)

        if selectedAction is None:
            return

        if selectedAction == a1:
            cbStr = ToClipboard(self.value)
            cb = QtWidgets.QApplication.clipboard()
            cb.setText(cbStr)
        elif selectedAction == a2:
            OpenMetadataDialog(self.nodeInput, metadata)
        elif isLocalFile and selectedAction == a3:
            OpenFileWithSystem(filePath)
        elif isLocalFile and selectedAction == a4:
            OpenFileInFolderWithSystem(filePath)


def MakeValueProxyWidget(widget, value, nodeInput):
    layout = QtWidgets.QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(widget)

    proxy = ValueProxyWidget(value, nodeInput)
    proxy.setLayout(layout)
    return proxy


class AlphaWidget(QtWidgets.QLabel):

    def __init__(self, alphaFloat):
        super().__init__()
        self.alphaFloat = alphaFloat

    def paintEvent(self, _):
        painter = QtGui.QPainter(self)

        rect = self.rect()
        width = rect.width()
        height = rect.height()

        # White -> black gradient
        gradient = QtGui.QLinearGradient(0, 0, 0, height)
        gradient.setColorAt(0, QtGui.QColor("#ffffff"))
        gradient.setColorAt(1, QtGui.QColor("#000000"))
        painter.fillRect(QtCore.QRect(0, 0, width, height), gradient)

        # Magenta line for alpha value
        lineY = height * (1.0 - self.alphaFloat)
        pen = QtGui.QPen(QtGui.QColor("magenta"))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawLine(0, lineY, width, lineY)

        # Draw 1px black border manually
        pen = QtGui.QPen(QtGui.QColor("black"))
        pen.setWidth(1)
        painter.setPen(pen)
        borderRect = self.rect().adjusted(0, 0, 0, 0)
        painter.drawRect(borderRect)


def MakeColorValueWidget(value, isColor4):
    valueLayout = QtWidgets.QHBoxLayout()
    valueLayout.setSpacing(6)
    valueLayout.setContentsMargins(0, 0, 0, 0)

    maxValue = max(value[0], value[1], value[2])
    isNormalized = maxValue <= 1.0

    # Values can technically be > 1.0, but we still want to show them
    normValue = Gf.Vec3f(value[0], value[1], value[2]) # copy by value

    if maxValue > 1.0:
        normValue /= maxValue

    hexStr = '#%02x%02x%02x' % (int(normValue[0] * 255.0),
                                int(normValue[1] * 255.0),
                                int(normValue[2] * 255.0))

    if isNormalized:
        labelStr = hexStr
        tooltipStr = labelStr
    else:
        rStr = FormatFloatShort(value[0], 2)
        gStr = FormatFloatShort(value[1], 2)
        bStr = FormatFloatShort(value[2], 2)
        labelStr = f'rgb({rStr}, {gStr}, {bStr})'
        tooltipStr = f'rgb({value[0]}, {value[1]}, {value[2]})' # full precision

    labelWidget = QtWidgets.QLabel(labelStr)
    labelWidget.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
    labelWidget.setStyleSheet(BORDER_WIDGET_STYLE)
    labelWidget.setObjectName("ThisWidget")
    labelWidget.setToolTip(tooltipStr)
    valueLayout.addWidget(labelWidget)

    colRect = QtWidgets.QLabel()
    colRect.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
    colRect.setAutoFillBackground(True)
    colRect.setStyleSheet(f"QLabel {{ background-color: {hexStr}; border: 1px solid black; }}")
    colRect.setFixedSize(16, 16)
    colRect.setToolTip(tooltipStr)
    valueLayout.addWidget(colRect)

    # Two rectangles when alpha exists
    if isColor4:
        aRect = AlphaWidget(value[3])
        aRect.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        aRect.setAutoFillBackground(True)
        aRect.setFixedSize(16, 16)
        aRect.setToolTip(str(value[3]))
        valueLayout.addWidget(aRect)

    valueWidget = QtWidgets.QWidget()
    valueWidget.setLayout(valueLayout)

    return QtCore.Qt.Horizontal if isNormalized else QtCore.Qt.Vertical, valueWidget


def PixmapToBase64(pixmap):
    buffer = QtCore.QByteArray()
    qBuffer = QtCore.QBuffer(buffer)
    qBuffer.open(QtCore.QBuffer.WriteOnly)
    pixmap.save(qBuffer, 'PNG')
    qBuffer.close()
    return base64.b64encode(buffer.data()).decode('ascii')


def MakeAssetValueWidget(value):
    valueStr = value.resolvedPath
    if not valueStr:
        valueStr = value.path # fall back to unresolved path

    shortValueStr = valueStr
    if len(valueStr) > 24:
        shortValueStr = '…' + valueStr[-24:]

    labelWidget = QtWidgets.QLabel(shortValueStr)
    labelWidget.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
    labelWidget.setContentsMargins(0, 0, 0, 0)
    labelWidget.setStyleSheet(BORDER_WIDGET_STYLE)
    labelWidget.setObjectName("ThisWidget")
    labelWidget.setToolTip(valueStr)

    valueLayout = QtWidgets.QHBoxLayout()
    valueLayout.setSpacing(6)
    valueLayout.setContentsMargins(0, 0, 0, 0)
    valueLayout.addWidget(labelWidget)

    imgLoaded = False

    if Usd.GetVersion() >= (0, 24, 11):
        # Use asset resolver to support images inside USDZ containers
        resolver = Ar.GetResolver()
        asset = resolver.OpenAsset(Ar.ResolvedPath(valueStr))

        if asset:
            imgData = asset.GetBuffer()
            pixmap = QtGui.QPixmap()
            imgLoaded = pixmap.loadFromData(imgData)
    else:
        pixmap = QtGui.QPixmap(valueStr)
        imgLoaded = not pixmap.isNull()

    if not imgLoaded and oiioSupported:
        # If loading is a success, we don't need AR (OIIO doesn't have IOProxy in Python)
        img = oiio.ImageInput.open(valueStr)
        if img:
            spec = img.spec()
            imgData = img.read_image("uint8")
            img.close()

            qImg = QtGui.QImage(imgData, spec.width, spec.height, QtGui.QImage.Format_RGB888)
            pixmap = QtGui.QPixmap.fromImage(qImg)
            imgLoaded = True

    if imgLoaded:
        imgSize = 160

        # Don't occupy much memory, especially in base64 form
        pixmap = pixmap.scaled(
            imgSize, imgSize,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation
        )

        # We need to transfer the image via base64 to the tooltip, as Qt does not natively support EXR
        base64Str = PixmapToBase64(pixmap)

        imgView = QtWidgets.QLabel()
        imgView.setPixmap(pixmap)
        imgView.setScaledContents(True) # downsample instead of crop
        imgView.setFixedSize(16, 16)
        imgView.setStyleSheet(BORDER_WIDGET_STYLE)
        imgView.setObjectName("ThisWidget")
        imgView.setToolTip(f'<img width={imgSize} height={imgSize} src="data:image/png;base64,{base64Str}" />')

        valueLayout.addWidget(imgView)

    valueWidget = QtWidgets.QWidget()
    valueWidget.setLayout(valueLayout)

    return QtCore.Qt.Vertical, valueWidget


def MakeVectorValueWidget(value):
    valueStr = ToString(value)

    layout = QtWidgets.QHBoxLayout()
    layout.setSpacing(0)
    layout.setContentsMargins(4, 2, 4, 2)

    minValue = float('inf')
    maxValue = 0.0

    vecStr = '[ '

    for i in range(0, value.dimension):
        v = value[i]

        minValue = min(v, minValue)
        maxValue = max(v, maxValue)

        if type(v) is float:
            shortValueStr = FormatFloatShort(v)
        else:
            shortValueStr = ToString(v)

        vecStr += shortValueStr

        # divider
        if i < (value.dimension - 1):
            vecStr += ', '

    vecStr += ' ]'

    vecWidget = QtWidgets.QLabel(vecStr)
    layout.addWidget(vecWidget)

    widget = QtWidgets.QWidget()
    widget.setLayout(layout)
    widget.setToolTip(valueStr)
    widget.setStyleSheet(BORDER_WIDGET_STYLE)
    widget.setObjectName("ThisWidget")

    orientation = QtCore.Qt.Horizontal

    hasShortValues = minValue > 0.01 and maxValue < 100

    if value.dimension > 3 or (value.dimension == 3 and not hasShortValues):
        orientation = QtCore.Qt.Vertical

    return orientation, widget


def MakeMatrixValueWidget(value):
    gridLayout = QtWidgets.QGridLayout()
    gridLayout.setContentsMargins(6, 6, 6, 6)

    if type(value) is Gf.Matrix2d:
        dim = 2
    elif type(value) is Gf.Matrix3d:
        dim = 3
    elif type(value) is Gf.Matrix4d:
        dim = 4

    for row in range(dim):
        for col in range(dim):
            s = FormatFloatShort(value[row][col], 2)
            gridLayout.addWidget(QtWidgets.QLabel(s), row, col)

    widget = QtWidgets.QWidget()
    widget.setLayout(gridLayout)
    widget.setToolTip(ToString(value))
    widget.setStyleSheet(BORDER_WIDGET_STYLE)
    widget.setObjectName("ThisWidget")

    return widget


def MakeValueStr(value, typeName):
    if Usd.GetVersion() >= (0, 23, 11):
        isPathExpression = (typeName == Sdf.ValueTypeNames.PathExpression)
    else:
        isPathExpression = False

    if typeName == Sdf.ValueTypeNames.Float:
        return FormatFloatShort(value)
    elif typeName == Sdf.ValueTypeNames.Bool or typeName == Sdf.ValueTypeNames.Int:
        return ToString(value)
    elif typeName == Sdf.ValueTypeNames.String or typeName == Sdf.ValueTypeNames.Token or isPathExpression:
        if isPathExpression:
            valueStr = value.GetText()
        else:
            valueStr = f'\"{value}\"'
        if len(valueStr) > 28:
            valueStr = valueStr[:28] + '…'
        return valueStr
    elif typeName == Sdf.ValueTypeNames.TimeCode:
        return FormatFloatShort(value.GetValue())
    elif typeName == Sdf.ValueTypeNames.Opaque:
        return '???'
    else:
        print(f"WARNING: unhandled type {str(typeName)}", file=sys.stderr)
        return ToString(value)


class ValueArrayDialog(QtWidgets.QDialog):

    def __init__(self, values):
        super().__init__()

        self.setWindowTitle('Array Values')

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
    if PySideModule == 'PySide6':
        d.exec()
    else:
        d.exec_()


def MakeArrayValueWidget(value):
    button = QtWidgets.QPushButton('Array')
    button.setToolTip('Show Array')
    button.setStyleSheet(ARRAY_BUTTON_STYLE)
    button.clicked.connect(lambda *args, v=value: ShowValueArrayDialog(v))
    return button


def MakeValueWidget(value, typeName):

    isColor3 = typeName in { Sdf.ValueTypeNames.Color3f, Sdf.ValueTypeNames.Color3d, Sdf.ValueTypeNames.Color3h }
    isColor4 = typeName in { Sdf.ValueTypeNames.Color4f, Sdf.ValueTypeNames.Color4d, Sdf.ValueTypeNames.Color4h }
    isMatrix = typeName in { Sdf.ValueTypeNames.Matrix2d, Sdf.ValueTypeNames.Matrix3d, Sdf.ValueTypeNames.Matrix4d }

    isVector = typeName in {
        Sdf.ValueTypeNames.Frame4d,
        Sdf.ValueTypeNames.Quatd, Sdf.ValueTypeNames.Quatf, Sdf.ValueTypeNames.Quath,
        Sdf.ValueTypeNames.Double2, Sdf.ValueTypeNames.Double3, Sdf.ValueTypeNames.Double4,
        Sdf.ValueTypeNames.Float2, Sdf.ValueTypeNames.Float3, Sdf.ValueTypeNames.Float4,
        Sdf.ValueTypeNames.Half2, Sdf.ValueTypeNames.Half3, Sdf.ValueTypeNames.Half4,
        Sdf.ValueTypeNames.Int2, Sdf.ValueTypeNames.Int3, Sdf.ValueTypeNames.Int4,
        Sdf.ValueTypeNames.Point3d, Sdf.ValueTypeNames.Point3f, Sdf.ValueTypeNames.Point3h,
        Sdf.ValueTypeNames.Normal3d, Sdf.ValueTypeNames.Normal3f, Sdf.ValueTypeNames.Normal3h,
        Sdf.ValueTypeNames.Vector3d, Sdf.ValueTypeNames.Vector3f, Sdf.ValueTypeNames.Vector3h,
        Sdf.ValueTypeNames.TexCoord2d, Sdf.ValueTypeNames.TexCoord2f, Sdf.ValueTypeNames.TexCoord2h,
        Sdf.ValueTypeNames.TexCoord3d, Sdf.ValueTypeNames.TexCoord3f, Sdf.ValueTypeNames.TexCoord3h
    }

    orientation = QtCore.Qt.Horizontal

    if isColor3 or isColor4:
        orientation, widget = MakeColorValueWidget(value, isColor4)
    elif isMatrix:
        widget = MakeMatrixValueWidget(value)
    elif isVector:
        orientation, widget = MakeVectorValueWidget(value)
    elif typeName == Sdf.ValueTypeNames.Asset:
        orientation, widget = MakeAssetValueWidget(value)
    elif typeName.isArray:
        widget = MakeArrayValueWidget(value)
    else:
        valueStr = MakeValueStr(value, typeName)
        toolTipStr = valueStr

        if typeName == Sdf.ValueTypeNames.String or typeName == Sdf.ValueTypeNames.Token:
            if len(value) > 10:
                orientation = QtCore.Qt.Vertical
            toolTipStr = f'\"{value}\"' # unshortened

        elif typeName == Sdf.ValueTypeNames.Float:
            toolTipStr = ToString(value) # full precision

        widget = QtWidgets.QLabel(valueStr)
        widget.setToolTip(toolTipStr)
        widget.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        widget.setStyleSheet(BORDER_WIDGET_STYLE)
        widget.setObjectName("ThisWidget")

    return orientation, widget


def MakePortRowWidget(name, typeName, value, port, portType):
    nameRlAlign = QtCore.Qt.AlignRight if portType == PortType.OUTPUT else QtCore.Qt.AlignLeft

    nameWidget = QtWidgets.QLabel(name)
    nameWidget.setToolTip(str(typeName))
    nameWidget.setAlignment(nameRlAlign | QtCore.Qt.AlignVCenter)

    if value is None or (port is not None and port.HasConnectedSource()):
        return nameWidget, nameWidget

    orientation, valueWidget = MakeValueWidget(value, typeName)

    valueWidget = MakeValueProxyWidget(valueWidget, value, port)

    if orientation == QtCore.Qt.Horizontal:
        rowLayout = QtWidgets.QHBoxLayout()
    else:
        rowLayout = QtWidgets.QVBoxLayout()
    rowLayout.setSpacing(6)
    rowLayout.setContentsMargins(0, 0, 0, 0)

    rowLayout.addWidget(nameWidget)
    rowLayout.addWidget(valueWidget)

    rowWidget = QtWidgets.QWidget()
    rowWidget.setLayout(rowLayout)

    return rowWidget, nameWidget


def MakePortWidget(port, portType):
    name = port.GetBaseName()
    typeName = port.GetTypeName()
    value = None if type(port) == UsdShade.Output else port.Get()
    return MakePortRowWidget(name, typeName, value, port, portType)


def MakePropertyWidget(attr):
    name = attr.GetBaseName()
    typeName = attr.GetTypeName()
    value = attr.Get()
    return MakePortRowWidget(name, typeName, value, None, PortType.INPUT)


class ShaderNode(GraphNode):

    def AddBody(self, inputs, outputs, props):
        portLayout = QtWidgets.QVBoxLayout()
        portLayout.setContentsMargins(8, 10, 8, 8)
        portLayout.setSpacing(6)

        # Sort columns alphanumerically for readability and consistency
        inputs.sort(key=lambda x: x.GetBaseName())
        outputs.sort(key=lambda x: x.GetBaseName())
        if props:
            props.sort(key=lambda x: x.GetBaseName())

        for i in inputs:
            hasUpstream = i.HasConnectedSource()
            name = i.GetBaseName()

            if not hasUpstream and (type(i) != UsdShade.Output and i.Get() is None):
                # Input is defined on the prim but not assigned any value
                continue

            nodeTypeBlacklist = [
                NodeType.UNKNOWN,
                NodeType.NODE_GRAPH,
                NodeType.MDL
            ]

            # skip input values if they match the default values
            if self.shaderOrNG and not hasUpstream and self.nodeType not in nodeTypeBlacklist:
                reg = Sdr.Registry()
                ndId = self.shaderOrNG.GetShaderId()
                if ndId:
                    nd = reg.GetShaderNodeByIdentifier(ndId)
                    if nd:
                        if Usd.GetVersion() >= (0, 25, 5):
                            ndInput = nd.GetShaderInput(name)
                        else:
                            ndInput = nd.GetInput(name)

                        # TODO: compare floats with epsilon
                        if ndInput is not None and i.Get() == ndInput.GetDefaultValue():
                            continue

            rowWidget, nameWidget = MakePortWidget(i, PortType.INPUT)

            portLayout.addWidget(rowWidget)

            self.inputPortWidgets[name] = nameWidget

        # Show properties as inputs
        if props:
            for p in props:
                name = p.GetBaseName()
                rowWidget, nameWidget = MakePropertyWidget(p)
                portLayout.addWidget(rowWidget)
                self.inputPortWidgets[name] = nameWidget

        for i in outputs:
            name = i.GetBaseName()

            if self.nodeType == NodeType.PARENT_INPUTS:
                rowWidget, nameWidget = MakePortWidget(i, PortType.OUTPUT)
                portLayout.addWidget(rowWidget)
                self.outputPortWidgets[name] = rowWidget

            # We only show outputs if their name is non-standard, indicating that there are multiple
            elif not IsDefaultOutputPortName(name):
                nameWidget = QtWidgets.QLabel(name)
                nameWidget.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                portLayout.addWidget(nameWidget)
                self.outputPortWidgets[name] = nameWidget

            else:
                self.outputPortWidgets[name] = self

        # Avoid whitespace because of paddding and margin when no input exists
        if portLayout.count():
            layout = self.layout()
            layout.addLayout(portLayout)

    def AuxButtonPressed(self):
        if self.nodeType == NodeType.NODE_GRAPH:
            self.ngChangeCallback(self.shaderOrNG)
            return

        ndId = self.shaderOrNG.GetShaderId()
        if ndId is not None:
            OpenNodeDefDialog(ndId)

    def GetPortPosition(self, name, portType):
        x = 0 if portType == PortType.INPUT else self.width()

        if portType == PortType.INPUT:
            w = self.inputPortWidgets[name]
            p = w.rect().center()
            y = w.mapToParent(p).y()
        elif IsDefaultOutputPortName(name):
            y = self.height() / 2
        elif name in self.outputPortWidgets:
            w = self.outputPortWidgets[name]
            p = w.rect().center()
            y = w.mapToParent(p).y()
        else:
            y = self.height() / 2

        return QtCore.QPointF(x, y)

    def __init__(self, nodeName, nodeType, inputs, outputs, ngChangeCallback = None, shaderOrNG = None, props = None):
        super().__init__()

        self.ngChangeCallback = ngChangeCallback
        self.shaderOrNG = shaderOrNG
        self.nodeType = nodeType

        # We use these widgets to get the positions that the connector
        # widgets connect to (after layouting).
        self.inputPortWidgets = {}
        self.outputPortWidgets = {}

        if self.nodeType == NodeType.MDL:
            typeName = "<MDL source file>"
        elif self.nodeType in [ NodeType.NODE_GRAPH, NodeType.PARENT_INPUTS, NodeType.PARENT_OUTPUTS ]:
            typeName = "<node graph>"
        elif self.nodeType == NodeType.UNKNOWN:
            typeName = "<missing>"
        else:
            reg = Sdr.Registry()
            ndId = self.shaderOrNG.GetShaderId()
            nd = reg.GetShaderNodeByIdentifier(ndId)
            family = nd.GetFamily()
            # Fall back to ND if no family exists
            typeName = family if family is not None else ndId

        if self.nodeType == NodeType.NODE_GRAPH:
            auxButtonText = "E"
            auxButtonTooltip = "Enter Node Graph"
        elif self.nodeType not in [ NodeType.UNKNOWN, NodeType.MDL, NodeType.PARENT_INPUTS, NodeType.PARENT_OUTPUTS ]:
            auxButtonText = "?"
            auxButtonTooltip = "Show Node Definition"
        else:
            auxButtonText = ""
            auxButtonTooltip = ""

        headerColor = NodeColors[self.nodeType]

        self.AddHeader(nodeName, typeName, headerColor, auxButtonText, auxButtonTooltip)
        self.AddBody(inputs, outputs, props)


def MakeSdrShaderNode(prim, ngChangeCallback):
    shaderOrNG = UsdShade.Shader(prim)
    if not shaderOrNG:
        shaderOrNG = UsdShade.NodeGraph(prim)

    nodeName = prim.GetName()
    nodeType = GetShaderNodeType(shaderOrNG)

    props = None
    if nodeType == NodeType.MDL:
        mdlPrefixPred = lambda name: name.startswith("info:mdl:")
        props = prim.GetProperties(mdlPrefixPred)

    inputs = shaderOrNG.GetInputs()
    outputs = shaderOrNG.GetOutputs()

    return ShaderNode(nodeName, nodeType, inputs, outputs, ngChangeCallback, shaderOrNG, props)


def MakeNgInputNode(nodeGraph, inputs):
    nodeName = nodeGraph.GetPrim().GetName()
    return ShaderNode(nodeName, NodeType.PARENT_INPUTS, [], inputs)


def MakeNgOutputNode(nodeGraph, outputs):
    nodeName = nodeGraph.GetPrim().GetName()
    return ShaderNode(nodeName, NodeType.PARENT_OUTPUTS, outputs, [])


class ConnectionWidget:

    def __init__(self, startNode, outputName, endNode, inputName):
        super().__init__()
        self.startNode = startNode
        self.endNode = endNode
        self.outputName = outputName
        self.inputName = inputName

        self.startNode.geometryChanged.connect(self.UpdateGeometry)
        self.endNode.geometryChanged.connect(self.UpdateGeometry)

        self.setPen(QtGui.QPen(QtCore.Qt.white, 1.0))
        self.UpdateGeometry()

    def UpdateGeometry(self):
        outputPos = self.startNode.widget().GetPortPosition(self.outputName, PortType.OUTPUT)
        inputPos = self.endNode.widget().GetPortPosition(self.inputName, PortType.INPUT)

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


class GraphView(QtWidgets.QGraphicsView):
    MIN_SCALE = 0.05
    MAX_SCALE = 20.0
    KEY_ZOOM_STEP = 1.2

    def __init__(self):
        super().__init__()

        self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self.setRenderHints(QtGui.QPainter.Antialiasing |
                            QtGui.QPainter.TextAntialiasing |
                            QtGui.QPainter.SmoothPixmapTransform)
        # Fix background not updating when window is hovering on top
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.FullViewportUpdate)

        # HW acceleration greatly speeds up spline rendering and has better AA
        if enableHwAcceleration:
            glFormat = QGLFormat()
            glFormat.setSamples(8) # MSAA
            if PySideModule != 'PySide6':
                glFormat.setSampleBuffers(True)

            if PySideModule == 'PySide6':
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
            factor = 1.0015 ** angleDelta
        elif pixelDelta != 0:
            factor = 1.005 ** pixelDelta
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
        scaleFactor = 4.0 # Higher values = larger resolution = less aliasing

        self.scene.clearSelection()
        self.scene.setSceneRect(self.scene.itemsBoundingRect())

        imageSize = self.scene.sceneRect().size().toSize()
        image = QtGui.QImage(imageSize * scaleFactor, QtGui.QImage.Format_ARGB32)
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

        return [] # (should not happen)

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
                    t = (0, set()) # depth, input name

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

        columns = [QtWidgets.QGraphicsLinearLayout(QtCore.Qt.Vertical)
                   for _ in range(maxDepth)]
        for column in columns:
            column.addStretch()

        def AddProxyWidgetToColumn(widget, columnIndex):
            proxy = QtWidgets.QGraphicsProxyWidget()
            proxy.setWidget(widget)
            proxy.setZValue(1) # Render nodes on top of lines
            columns[columnIndex].addItem(proxy)
            return proxy

        # Insert the node representing the parent node graph inputs
        for ngPrim, (depth, inputNames) in self.parentNgInputMap.items():
            nodeGraph = UsdShade.NodeGraph(ngPrim)
            ngInputs = [nodeGraph.GetInput(name) for name in inputNames]
            w = MakeNgInputNode(nodeGraph, ngInputs)

            columnIndex = maxDepth - depth - 1
            self.parentNgWidgetMap[ngPrim] = AddProxyWidgetToColumn(
                w, columnIndex)

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
                continue # Should only happen in the case of circular graphs

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
                startNode, outputPortName, endNode, inputPortName)
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
        rootInputs = nodeGraph.GetOutputs() if selectedOutput is None else [ selectedOutput ]

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
        self.graphLayout = QtWidgets.QGraphicsLinearLayout(QtCore.Qt.Horizontal)
        self.graphLayout.setContentsMargins(22, 22, 22, 22)
        self.graphLayout.setSpacing(64)

        self.maxDepth = 0
        self.nodeMap = {} # [prim, depth]
        self.parentNgInputMap = {} # used parent node graph inputs
        self.parentNgWidgetMap = {} # [prim, node widget]
        self.BuildNodeMap(rootPrim, rootInputs, 0)

        self.widgetMap = {} # [prim, node widget]
        self.AddNodesToLayout()

        self.nodeMap = {}
        self.AddNodeConnections(rootPrim, rootInputs, 0)

        graphWidget = QtWidgets.QGraphicsWidget()
        graphWidget.setLayout(self.graphLayout)
        self.scene.addItem(graphWidget)

        self.graphView.setScene(self.scene)
        self.UpdateNodeFilterTargets()

    def GetAllNodeProxies(self):
        return (list(self.widgetMap.values())
                + list(self.parentNgWidgetMap.values()))

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
        return (event.key() in (QtCore.Qt.Key.Key_F, QtCore.Qt.Key.Key_A)
                and event.modifiers() in (QtCore.Qt.NoModifier,
                                          QtCore.Qt.KeypadModifier))

    def IsZoomKey(self, event):
        zoomKeys = (QtCore.Qt.Key.Key_Plus, QtCore.Qt.Key.Key_Equal,
                    QtCore.Qt.Key.Key_Minus, QtCore.Qt.Key.Key_Underscore)
        return (event.key() in zoomKeys
                and event.modifiers() in (QtCore.Qt.NoModifier,
                                          QtCore.Qt.ShiftModifier,
                                          QtCore.Qt.KeypadModifier))

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

        return (widget is self.graphView.viewport()
                or widget in self.nodeFilterTargets)

    def HandleKeyPress(self, event):
        key = event.key()

        if key == QtCore.Qt.Key.Key_F:
            self.FrameSelected()
        elif key == QtCore.Qt.Key.Key_A:
            self.FrameAll()
        elif key in (QtCore.Qt.Key.Key_Plus, QtCore.Qt.Key.Key_Equal):
            self.ZoomIn()
        elif key in (QtCore.Qt.Key.Key_Minus,
                     QtCore.Qt.Key.Key_Underscore):
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
            if (event.button() == QtCore.Qt.LeftButton
                    and obj is self.graphView.viewport()):
                item = self.graphView.itemAt(event.pos())
                if item in self.GetAllNodeProxies():
                    self.SelectNode(item, event.modifiers())
                else:
                    self.ClearSelection()

        return super().eventFilter(obj, event)


class GraphDockWidget(QtWidgets.QDockWidget):
    DOCK_OBJECT_NAME = "usdshadeviewDock"
    DEFAULT_TITLE = "UsdShade Node Graph"

    def ShowBakeMtlxDialog(self):
        material = UsdShade.Material(self.nodeGraph)
        self.bakeMtlxDialog = BakeMtlxDialog(material)
        self.bakeMtlxDialog.show()

    def ShowExportAsImageDialog(self):
        # NOTE: on macOS there's an issue where the main window is incorrectly focused after close
        filePath, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save File",
            "graph.png",  # default dir = CWD
            "Images (*.png *.webp);;All Files (*)"
        )

        if filePath:
            image = self.graphWidget.RenderSceneToImage()
            image.save(filePath)

    def AddViewAction(self, menu, text, shortcut, callback):
        action = menu.addAction(text)
        action.setShortcut(QtGui.QKeySequence(shortcut))
        # The graph keys are handled contextually by GraphWidget; keeping
        # this scoped avoids clashing with usdview's global shortcuts.
        action.setShortcutContext(QtCore.Qt.WidgetShortcut)
        action.triggered.connect(callback)
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

        self.AddViewAction(viewMenu, "Frame Selected", "F",
                           self.graphWidget.FrameSelected)
        self.AddViewAction(viewMenu, "Frame All", "A",
                           self.graphWidget.FrameAll)
        self.AddViewAction(viewMenu, "Zoom In", "+",
                           self.graphWidget.ZoomIn)
        self.AddViewAction(viewMenu, "Zoom Out", "-",
                           self.graphWidget.ZoomOut)
        viewMenu.addSeparator()

        outputMenu = viewMenu.addMenu("Filter Output")

        noneOutputAction = outputMenu.addAction('None')
        noneOutputAction.setCheckable(True)
        noneOutputAction.setChecked(self.selectedOutput is None)
        noneOutputAction.triggered.connect(lambda *args: self.SwitchToOutput(None))
        outputMenu.addSeparator()

        outputs = self.nodeGraph.GetOutputs()

        for output in outputs:
            name = output.GetBaseName()
            a = outputMenu.addAction(name)
            a.setCheckable(True)
            a.setChecked(output == self.selectedOutput)
            a.triggered.connect(lambda *args, o=output: self.SwitchToOutput(o))

        toolsMenu = menuBar.addMenu("Tools")

        isMaterial = self.nodeGraph.GetPrim().IsA(UsdShade.Material)
        if isMaterial and mtlxSupported and self.selectedOutput is not None:
            outputName = self.selectedOutput.GetBaseName()

            if outputName == 'mtlx:surface':
                a = toolsMenu.addAction("Bake to Texture...")
                a.triggered.connect(self.ShowBakeMtlxDialog)

        exportAction = toolsMenu.addAction("Export as Image...")
        exportAction.triggered.connect(self.ShowExportAsImageDialog)

        self.contentLayout.setMenuBar(menuBar)

    def BackToParentNodeGraph(self):
        self.nodeGraph, self.selectedOutput = self.historyStack.pop()
        self.UpdateContentForOutput()

    def SwitchToOutput(self, output):
        if output == self.selectedOutput:
            return # Already showing, don't reset viewport
        self.selectedOutput = output
        self.UpdateContentForOutput()

    def UpdateContentForOutput(self):
        primPath = str(self.nodeGraph.GetPrim().GetPath())
        outputStr = ''
        if self.selectedOutput is not None:
            outputStr = f' ({self.selectedOutput.GetBaseName()})'

        self.setWindowTitle(
            f"{self.DEFAULT_TITLE}: {primPath}{outputStr}")

        self.graphWidget.PopulateScene(self.nodeGraph, self.selectedOutput)

        self.UpdateMenuBar()

    def GetDefaultOutput(self):
        # For materials, we try to select the 'surface' output. For NGs, none.
        if self.nodeGraph.GetPrim().IsA(UsdShade.Material):
            outputs = self.nodeGraph.GetOutputs()

            for output in outputs:
                if 'surface' in output.GetBaseName():
                    return output
        return None

    def SetNodeGraph(self, nodeGraph):
        # Store old NGs on a stack so that we can navigate back using the menu
        if self.nodeGraph is not None and nodeGraph != self.nodeGraph:
            self.historyStack.append((self.nodeGraph, self.selectedOutput))

        self.nodeGraph = nodeGraph
        self.selectedOutput = self.GetDefaultOutput()

        self.placeholderLabel.hide()
        self.graphWidget.show()

        self.UpdateContentForOutput()

    def __init__(self, mainWindow):
        super().__init__(self.DEFAULT_TITLE, mainWindow)

        self.setObjectName(self.DOCK_OBJECT_NAME)
        self.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
        self.setFeatures(
            QtWidgets.QDockWidget.DockWidgetClosable
            | QtWidgets.QDockWidget.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFloatable)

        contentWidget = QtWidgets.QWidget(self)
        self.contentLayout = QtWidgets.QVBoxLayout(contentWidget)
        self.contentLayout.setContentsMargins(0, 0, 0, 0)

        self.placeholderLabel = QtWidgets.QLabel(
            "Right-click a Material or NodeGraph prim and choose "
            "\"Show Node Graph\".",
            contentWidget)
        self.placeholderLabel.setAlignment(QtCore.Qt.AlignCenter)
        self.contentLayout.addWidget(self.placeholderLabel, 1)

        self.graphWidget = GraphWidget(self.SetNodeGraph)
        self.contentLayout.addWidget(self.graphWidget, 1)
        self.setWidget(contentWidget)
        self.graphWidget.hide()

        self.nodeGraph = None
        self.historyStack = [] # push (ng, output) when we traverse into child NG

        self.resize(800, 600) # set default size

    def ShowNodeGraph(self, nodeGraph):
        if nodeGraph != self.nodeGraph:
            self.SetNodeGraph(nodeGraph)
        self.show()
        self.raise_()

        # On Windows there's a bug where the scroll bars initially don't show.
        if platform.system() == 'Windows':
            QtCore.QTimer.singleShot(0, self.ForceInitialResize)

    def ForceInitialResize(self):
        size = self.size()
        self.resize(size.width() + 1, size.height())
        self.resize(size)


class UsdShadeViewDockState(StateSource):
    """Persists the node graph dock layout in usdview's state file."""

    def __init__(self, settings, mainWindow, dockWidget):
        super().__init__(settings, "usdshadeview")

        self._mainWindow = mainWindow
        self._dockWidget = dockWidget

        self.dockState = self.stateProperty("dockState", default="")
        self.dockVisible = self.stateProperty("dockVisible", default=False)

    def Restore(self):
        if self.dockState:
            state = QtCore.QByteArray.fromBase64(
                self.dockState.encode("ascii"))
            if not self._mainWindow.restoreState(state):
                print("WARNING: failed to restore usdshadeview dock state",
                      file=sys.stderr)

        self._dockWidget.setVisible(self.dockVisible)

    def onSaveState(self, state):
        state["dockState"] = base64.b64encode(
            self._mainWindow.saveState().data()).decode("ascii")
        state["dockVisible"] = self._dockWidget.isVisible()


class ShowUsdShadeGraphContextMenuItem(PrimContextMenuItem):

    def __init__(self, appController, item, usdviewApi, viewContainer):
        super().__init__(appController, item)
        self.usdviewApi = usdviewApi
        self.viewContainer = viewContainer

    def GetFocusedPrim(self):
        return self.usdviewApi.prim

    def IsEnabled(self):
        prim = self.GetFocusedPrim()
        return prim.IsA(UsdShade.Material) or prim.IsA(UsdShade.NodeGraph)

    def GetText(self):
        return "Show Node Graph"

    def RunCommand(self):
        prim = self.GetFocusedPrim()
        nodeGraph = UsdShade.NodeGraph(prim) # UsdShade.Material inherits from NodeGraph
        outputs = nodeGraph.GetOutputs()

        if not outputs:
            return

        self.viewContainer.ShowNodeGraph(nodeGraph)


class UsdShadeViewContainer(PluginContainer):
    SDR_NODES_COMMAND_NS = "UsdShadeView.SdrNodes"
    TOGGLE_DOCK_COMMAND_NS = "UsdShadeView.ToggleDock"

    def registerPlugins(self, plugRegistry, usdviewApi):
        self.usdviewApi = usdviewApi
        self.dockWidget = None
        self.sdrNodesMenu = plugRegistry.registerCommandPlugin(
            self.SDR_NODES_COMMAND_NS,
            "List of Sdr nodes",
            lambda *args: None)
        self.toggleDockCommand = plugRegistry.registerCommandPlugin(
            self.TOGGLE_DOCK_COMMAND_NS,
            "UsdShade Node Graph",
            lambda *args: self.ToggleDock(),
            "Show or hide the UsdShade node graph panel.")

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
                    lambda *args, n=ndId: OpenNodeDefDialog(n))
                sdrNodeMenu.addItem(item)

        self.CreateDockWidget(windowMenu)
        self.hijackPrimContextMenu()

    def CreateDockWidget(self, windowMenu):
        mainWindow = self.usdviewApi.qMainWindow

        self.dockWidget = GraphDockWidget(mainWindow)
        mainWindow.addDockWidget(
            QtCore.Qt.RightDockWidgetArea, self.dockWidget)

        dockAction = windowMenu.addItem(self.toggleDockCommand)
        dockAction.setCheckable(True)
        dockAction.setChecked(self.dockWidget.isVisible())
        self.dockWidget.visibilityChanged.connect(dockAction.setChecked)

        dockState = UsdShadeViewDockState(
            self.GetSettingsSource(), mainWindow, self.dockWidget)
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
                appController, item, usdviewApi, viewContainer)

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

if enableHwAcceleration and platform.system() == 'Darwin':
    QtCore.qInstallMessageHandler(customMessageHandler)
