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

"""Node widgets and their factory functions."""

from pxr import Sdr, Usd, UsdShade
from pxr.Usdviewq.qt import QtCore, QtWidgets

from .constants import (
    AUX_BUTTON_STYLE,
    BORDER_WIDGET_STYLE,
    SELECTED_NODE_STYLE,
    NodeColors,
    NodeType,
    PortType,
)
from .dialogs import OpenNodeDefDialog
from .utils import GetShaderNodeType, IsDefaultOutputPortName
from .value_widgets import MakePortWidget, MakePropertyWidget


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
            SELECTED_NODE_STYLE if selected else BORDER_WIDGET_STYLE
        )

    def AddHeader(
        self, title, subtitle, color, auxButtonText="", auxButtonTooltip=""
    ):
        nameLabel = QtWidgets.QLabel(title)
        typeLabel = QtWidgets.QLabel(subtitle)
        typeLabel.setStyleSheet(
            "QLabel { font-style: italic; font-weight: 100; }"
        )

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
        headerFrame.setStyleSheet(
            f"QFrame {{ background-color: {color.value}; color: #000; }}"
        )

        self.layout().addWidget(headerFrame)


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

            if not hasUpstream and (
                type(i) != UsdShade.Output and i.Get() is None
            ):
                # Input is defined on the prim but not assigned any value
                continue

            nodeTypeBlacklist = [
                NodeType.UNKNOWN,
                NodeType.NODE_GRAPH,
                NodeType.MDL,
            ]

            # skip input values if they match the default values
            if (
                self.shaderOrNG
                and not hasUpstream
                and self.nodeType not in nodeTypeBlacklist
            ):
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
                        if (
                            ndInput is not None
                            and i.Get() == ndInput.GetDefaultValue()
                        ):
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

            elif self.showAllOutputPorts or not IsDefaultOutputPortName(name):
                nameWidget = QtWidgets.QLabel(name)
                nameWidget.setAlignment(
                    QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
                )
                portLayout.addWidget(nameWidget)
                self.outputPortWidgets[name] = nameWidget

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
        elif name in self.outputPortWidgets:
            w = self.outputPortWidgets[name]
            p = w.rect().center()
            y = w.mapToParent(p).y()
        else:
            y = self.height() / 2

        return QtCore.QPointF(x, y)

    def __init__(
        self,
        nodeName,
        nodeType,
        inputs,
        outputs,
        ngChangeCallback=None,
        shaderOrNG=None,
        props=None,
        showAllOutputPorts=False,
    ):
        super().__init__()

        self.ngChangeCallback = ngChangeCallback
        self.shaderOrNG = shaderOrNG
        self.nodeType = nodeType
        self.showAllOutputPorts = showAllOutputPorts

        # We use these widgets to get the positions that the connector
        # widgets connect to (after layouting).
        self.inputPortWidgets = {}
        self.outputPortWidgets = {}

        if self.nodeType == NodeType.MDL:
            typeName = "<MDL source file>"
        elif self.nodeType in [
            NodeType.NODE_GRAPH,
            NodeType.PARENT_INPUTS,
            NodeType.PARENT_OUTPUTS,
        ]:
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
        elif self.nodeType not in [
            NodeType.UNKNOWN,
            NodeType.MDL,
            NodeType.PARENT_INPUTS,
            NodeType.PARENT_OUTPUTS,
        ]:
            auxButtonText = "?"
            auxButtonTooltip = "Show Node Definition"
        else:
            auxButtonText = ""
            auxButtonTooltip = ""

        headerColor = NodeColors[self.nodeType]

        self.AddHeader(
            nodeName, typeName, headerColor, auxButtonText, auxButtonTooltip
        )
        self.AddBody(inputs, outputs, props)


def MakeSdrShaderNode(prim, ngChangeCallback, showAllOutputPorts=False):
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

    return ShaderNode(
        nodeName,
        nodeType,
        inputs,
        outputs,
        ngChangeCallback,
        shaderOrNG,
        props,
        showAllOutputPorts,
    )


def MakeNgInputNode(nodeGraph, inputs):
    nodeName = nodeGraph.GetPrim().GetName()
    return ShaderNode(nodeName, NodeType.PARENT_INPUTS, [], inputs)


def MakeNgOutputNode(nodeGraph, outputs):
    nodeName = nodeGraph.GetPrim().GetName()
    return ShaderNode(nodeName, NodeType.PARENT_OUTPUTS, outputs, [])
