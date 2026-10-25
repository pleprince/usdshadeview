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

"""Shared constants, colors and styles for the usdshadeview plugin."""

from enum import Enum

# Abortion criterium for circular node graphs
MAX_NODE_GRAPH_DEPTH = 80


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
