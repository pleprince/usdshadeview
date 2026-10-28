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

"""Widgets that render USD attribute values."""

import base64
import logging
import os

from pxr import Ar, Gf, Sdf, Usd, UsdShade
from pxr.Usdviewq.qt import QtCore, QtGui, QtWidgets
from pxr.Usdviewq.scalarTypes import ToClipboard, ToString

from .compat import PySideModule, oiio, oiioSupported
from .constants import (
    ARRAY_BUTTON_STYLE,
    MakeBorderWidgetStyle,
    MakeNodeBackgroundStyle,
    PortType,
    UIColors,
)
from .dialogs import OpenMetadataDialog, ShowValueArrayDialog
from .utils import (
    FormatFloatShort,
    IsOpenFileInFolderSupported,
    IsOpenFileWithSystemSupported,
    OpenFileInFolderWithSystem,
    OpenFileWithSystem,
)

logger = logging.getLogger(__name__)


# Sets up a context menu on a value widget
class ValueProxyWidget(QtWidgets.QWidget):
    def __init__(self, value, nodeInput, dialogParent=None):
        super().__init__()
        self.value = value
        self.nodeInput = nodeInput
        self.dialogParent = dialogParent
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

        isLocalFile = isinstance(self.value, Sdf.AssetPath) and os.path.exists(
            self.value.resolvedPath
        )

        a3 = None
        a4 = None
        if isLocalFile:
            filePath = self.value.resolvedPath

            if IsOpenFileWithSystemSupported():
                a3 = menu.addAction("Open File")

            if IsOpenFileInFolderSupported():
                a4 = menu.addAction("Open File in Folder")

        globalPos = self.mapToGlobal(position)
        if PySideModule == "PySide6":
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
            OpenMetadataDialog(self.nodeInput, metadata, self.dialogParent)
        elif isLocalFile and selectedAction == a3:
            OpenFileWithSystem(filePath)
        elif isLocalFile and selectedAction == a4:
            OpenFileInFolderWithSystem(filePath)


def MakeValueProxyWidget(
    widget,
    value,
    nodeInput,
    nodeBackgroundColor: str = UIColors.CHARCOAL.value,
    dialogParent=None,
):
    layout = QtWidgets.QHBoxLayout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(widget)

    proxy = ValueProxyWidget(value, nodeInput, dialogParent)
    proxy.setLayout(layout)
    proxy.setObjectName("NodeBackground")
    proxy.setStyleSheet(MakeNodeBackgroundStyle(nodeBackgroundColor))
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


def MakeColorValueWidget(
    value, isColor4, nodeBackgroundColor: str = UIColors.CHARCOAL.value
):
    valueLayout = QtWidgets.QHBoxLayout()
    valueLayout.setSpacing(6)
    valueLayout.setContentsMargins(0, 0, 0, 0)

    maxValue = max(value[0], value[1], value[2])
    isNormalized = maxValue <= 1.0

    # Values can technically be > 1.0, but we still want to show them
    normValue = Gf.Vec3f(value[0], value[1], value[2])  # copy by value

    if maxValue > 1.0:
        normValue /= maxValue

    hexStr = "#%02x%02x%02x" % (
        int(normValue[0] * 255.0),
        int(normValue[1] * 255.0),
        int(normValue[2] * 255.0),
    )

    if isNormalized:
        labelStr = hexStr
        tooltipStr = labelStr
    else:
        rStr = FormatFloatShort(value[0], 2)
        gStr = FormatFloatShort(value[1], 2)
        bStr = FormatFloatShort(value[2], 2)
        labelStr = f"rgb({rStr}, {gStr}, {bStr})"
        tooltipStr = (
            f"rgb({value[0]}, {value[1]}, {value[2]})"  # full precision
        )

    labelWidget = QtWidgets.QLabel(labelStr)
    labelWidget.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
    labelWidget.setObjectName("ThisWidget")
    labelWidget.setStyleSheet(MakeBorderWidgetStyle(nodeBackgroundColor))
    labelWidget.setToolTip(tooltipStr)
    valueLayout.addWidget(labelWidget)

    colRect = QtWidgets.QLabel()
    colRect.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
    colRect.setAutoFillBackground(True)
    colRect.setStyleSheet(
        f"QLabel {{ background-color: {hexStr}; border: 1px solid black; }}"
    )
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
    valueWidget.setObjectName("NodeBackground")
    valueWidget.setStyleSheet(MakeNodeBackgroundStyle(nodeBackgroundColor))

    return (
        QtCore.Qt.Horizontal if isNormalized else QtCore.Qt.Vertical,
        valueWidget,
    )


def PixmapToBase64(pixmap):
    buffer = QtCore.QByteArray()
    qBuffer = QtCore.QBuffer(buffer)
    qBuffer.open(QtCore.QBuffer.WriteOnly)
    pixmap.save(qBuffer, "PNG")
    qBuffer.close()
    return base64.b64encode(buffer.data()).decode("ascii")


def MakeAssetValueWidget(
    value, nodeBackgroundColor: str = UIColors.CHARCOAL.value
):
    valueStr = value.resolvedPath
    if not valueStr:
        valueStr = value.path  # fall back to unresolved path

    shortValueStr = valueStr
    if len(valueStr) > 24:
        shortValueStr = "…" + valueStr[-24:]

    labelWidget = QtWidgets.QLabel(shortValueStr)
    labelWidget.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
    labelWidget.setContentsMargins(0, 0, 0, 0)
    labelWidget.setObjectName("ThisWidget")
    labelWidget.setStyleSheet(MakeBorderWidgetStyle(nodeBackgroundColor))
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

            qImg = QtGui.QImage(
                imgData, spec.width, spec.height, QtGui.QImage.Format_RGB888
            )
            pixmap = QtGui.QPixmap.fromImage(qImg)
            imgLoaded = True

    if imgLoaded:
        imgSize = 160

        # Don't occupy much memory, especially in base64 form
        pixmap = pixmap.scaled(
            imgSize,
            imgSize,
            QtCore.Qt.KeepAspectRatio,
            QtCore.Qt.SmoothTransformation,
        )

        # We need to transfer the image via base64 to the tooltip, as Qt does not natively support EXR
        base64Str = PixmapToBase64(pixmap)

        imgView = QtWidgets.QLabel()
        imgView.setPixmap(pixmap)
        imgView.setScaledContents(True)  # downsample instead of crop
        imgView.setFixedSize(16, 16)
        imgView.setObjectName("ThisWidget")
        imgView.setStyleSheet(MakeBorderWidgetStyle(nodeBackgroundColor))
        imgView.setToolTip(
            f'<img width={imgSize} height={imgSize} src="data:image/png;base64,{base64Str}" />'
        )

        valueLayout.addWidget(imgView)

    valueWidget = QtWidgets.QWidget()
    valueWidget.setLayout(valueLayout)
    valueWidget.setObjectName("NodeBackground")
    valueWidget.setStyleSheet(MakeNodeBackgroundStyle(nodeBackgroundColor))

    return QtCore.Qt.Vertical, valueWidget


def MakeVectorValueWidget(
    value, nodeBackgroundColor: str = UIColors.CHARCOAL.value
):
    valueStr = ToString(value)

    layout = QtWidgets.QHBoxLayout()
    layout.setSpacing(0)
    layout.setContentsMargins(4, 2, 4, 2)

    minValue = float("inf")
    maxValue = 0.0

    vecStr = "[ "

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
            vecStr += ", "

    vecStr += " ]"

    vecWidget = QtWidgets.QLabel(vecStr)
    layout.addWidget(vecWidget)

    widget = QtWidgets.QWidget()
    widget.setLayout(layout)
    widget.setToolTip(valueStr)
    widget.setObjectName("ThisWidget")
    widget.setStyleSheet(MakeBorderWidgetStyle(nodeBackgroundColor))

    orientation = QtCore.Qt.Horizontal

    hasShortValues = minValue > 0.01 and maxValue < 100

    if value.dimension > 3 or (value.dimension == 3 and not hasShortValues):
        orientation = QtCore.Qt.Vertical

    return orientation, widget


def MakeMatrixValueWidget(
    value, nodeBackgroundColor: str = UIColors.CHARCOAL.value
):
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
    widget.setObjectName("ThisWidget")
    widget.setStyleSheet(MakeBorderWidgetStyle(nodeBackgroundColor))

    return widget


def MakeValueStr(value, typeName):
    if Usd.GetVersion() >= (0, 23, 11):
        isPathExpression = typeName == Sdf.ValueTypeNames.PathExpression
    else:
        isPathExpression = False

    if typeName == Sdf.ValueTypeNames.Float:
        return FormatFloatShort(value)
    elif (
        typeName == Sdf.ValueTypeNames.Bool
        or typeName == Sdf.ValueTypeNames.Int
    ):
        return ToString(value)
    elif (
        typeName == Sdf.ValueTypeNames.String
        or typeName == Sdf.ValueTypeNames.Token
        or isPathExpression
    ):
        if isPathExpression:
            valueStr = value.GetText()
        else:
            valueStr = f'"{value}"'
        if len(valueStr) > 28:
            valueStr = valueStr[:28] + "…"
        return valueStr
    elif typeName == Sdf.ValueTypeNames.TimeCode:
        return FormatFloatShort(value.GetValue())
    elif typeName == Sdf.ValueTypeNames.Opaque:
        return "???"
    else:
        logger.warning("Unhandled value type %s", typeName)
        return ToString(value)


def MakeArrayValueWidget(value, dialogParent=None):
    button = QtWidgets.QPushButton("Array")
    button.setToolTip("Show Array")
    button.setStyleSheet(ARRAY_BUTTON_STYLE)
    button.clicked.connect(
        lambda *args, v=value: ShowValueArrayDialog(v, dialogParent)
    )
    return button


def MakeValueWidget(
    value,
    typeName,
    nodeBackgroundColor: str = UIColors.CHARCOAL.value,
    dialogParent=None,
):

    isColor3 = typeName in {
        Sdf.ValueTypeNames.Color3f,
        Sdf.ValueTypeNames.Color3d,
        Sdf.ValueTypeNames.Color3h,
    }
    isColor4 = typeName in {
        Sdf.ValueTypeNames.Color4f,
        Sdf.ValueTypeNames.Color4d,
        Sdf.ValueTypeNames.Color4h,
    }
    isMatrix = typeName in {
        Sdf.ValueTypeNames.Matrix2d,
        Sdf.ValueTypeNames.Matrix3d,
        Sdf.ValueTypeNames.Matrix4d,
    }

    isVector = typeName in {
        Sdf.ValueTypeNames.Frame4d,
        Sdf.ValueTypeNames.Quatd,
        Sdf.ValueTypeNames.Quatf,
        Sdf.ValueTypeNames.Quath,
        Sdf.ValueTypeNames.Double2,
        Sdf.ValueTypeNames.Double3,
        Sdf.ValueTypeNames.Double4,
        Sdf.ValueTypeNames.Float2,
        Sdf.ValueTypeNames.Float3,
        Sdf.ValueTypeNames.Float4,
        Sdf.ValueTypeNames.Half2,
        Sdf.ValueTypeNames.Half3,
        Sdf.ValueTypeNames.Half4,
        Sdf.ValueTypeNames.Int2,
        Sdf.ValueTypeNames.Int3,
        Sdf.ValueTypeNames.Int4,
        Sdf.ValueTypeNames.Point3d,
        Sdf.ValueTypeNames.Point3f,
        Sdf.ValueTypeNames.Point3h,
        Sdf.ValueTypeNames.Normal3d,
        Sdf.ValueTypeNames.Normal3f,
        Sdf.ValueTypeNames.Normal3h,
        Sdf.ValueTypeNames.Vector3d,
        Sdf.ValueTypeNames.Vector3f,
        Sdf.ValueTypeNames.Vector3h,
        Sdf.ValueTypeNames.TexCoord2d,
        Sdf.ValueTypeNames.TexCoord2f,
        Sdf.ValueTypeNames.TexCoord2h,
        Sdf.ValueTypeNames.TexCoord3d,
        Sdf.ValueTypeNames.TexCoord3f,
        Sdf.ValueTypeNames.TexCoord3h,
    }

    orientation = QtCore.Qt.Horizontal

    if isColor3 or isColor4:
        orientation, widget = MakeColorValueWidget(
            value, isColor4, nodeBackgroundColor
        )
    elif isMatrix:
        widget = MakeMatrixValueWidget(value, nodeBackgroundColor)
    elif isVector:
        orientation, widget = MakeVectorValueWidget(
            value, nodeBackgroundColor
        )
    elif typeName == Sdf.ValueTypeNames.Asset:
        orientation, widget = MakeAssetValueWidget(
            value, nodeBackgroundColor
        )
    elif typeName.isArray:
        widget = MakeArrayValueWidget(value, dialogParent)
    else:
        valueStr = MakeValueStr(value, typeName)
        toolTipStr = valueStr

        if (
            typeName == Sdf.ValueTypeNames.String
            or typeName == Sdf.ValueTypeNames.Token
        ):
            if len(value) > 10:
                orientation = QtCore.Qt.Vertical
            toolTipStr = f'"{value}"'  # unshortened

        elif typeName == Sdf.ValueTypeNames.Float:
            toolTipStr = ToString(value)  # full precision

        widget = QtWidgets.QLabel(valueStr)
        widget.setToolTip(toolTipStr)
        widget.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        widget.setObjectName("ThisWidget")
        widget.setStyleSheet(MakeBorderWidgetStyle(nodeBackgroundColor))

    return orientation, widget


def MakePortRowWidget(
    name,
    typeName,
    value,
    port,
    portType,
    nodeBackgroundColor: str = UIColors.CHARCOAL.value,
    dialogParent=None,
):
    nameRlAlign = (
        QtCore.Qt.AlignRight
        if portType == PortType.OUTPUT
        else QtCore.Qt.AlignLeft
    )

    nameWidget = QtWidgets.QLabel(name)
    nameWidget.setToolTip(str(typeName))
    nameWidget.setAlignment(nameRlAlign | QtCore.Qt.AlignVCenter)

    if value is None or (port is not None and port.HasConnectedSource()):
        return nameWidget, nameWidget

    orientation, valueWidget = MakeValueWidget(
        value, typeName, nodeBackgroundColor, dialogParent
    )

    valueWidget = MakeValueProxyWidget(
        valueWidget,
        value,
        port,
        nodeBackgroundColor,
        dialogParent,
    )

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
    rowWidget.setObjectName("NodeBackground")
    rowWidget.setStyleSheet(MakeNodeBackgroundStyle(nodeBackgroundColor))

    return rowWidget, nameWidget


def MakePortWidget(
    port,
    portType,
    nodeBackgroundColor: str = UIColors.CHARCOAL.value,
    dialogParent=None,
):
    name = port.GetBaseName()
    typeName = port.GetTypeName()
    value = None if type(port) == UsdShade.Output else port.Get()
    return MakePortRowWidget(
        name,
        typeName,
        value,
        port,
        portType,
        nodeBackgroundColor,
        dialogParent,
    )


def MakePropertyWidget(
    attr,
    nodeBackgroundColor: str = UIColors.CHARCOAL.value,
    dialogParent=None,
):
    name = attr.GetBaseName()
    typeName = attr.GetTypeName()
    value = attr.Get()
    return MakePortRowWidget(
        name,
        typeName,
        value,
        None,
        PortType.INPUT,
        nodeBackgroundColor,
        dialogParent,
    )
