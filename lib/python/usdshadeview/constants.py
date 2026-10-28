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

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# Abortion criterium for circular node graphs
MAX_NODE_GRAPH_DEPTH = 80

# Fit view margin, in viewport pixels.
DEFAULT_FIT_VIEW_MARGIN = 20.0

# Vertical spacing between nodes in a graph column, in scene units.
DEFAULT_NODE_VERTICAL_SPACING = 6

# Keyboard shortcut for the "Show Node Graph" context menu action.
DEFAULT_SHOW_NODE_GRAPH_SHORTCUT = "Ctrl+M"


class UIColors(str, Enum):
    GOLD = "#c39a46"
    CHARCOAL = "#373737"  # usdviewstyle.qss QTable background
    MDL_GREEN = "#77AB47"
    DARK_GREY = "#2a2a2a"  # match usdviewstyle.qss
    LIGHT_RED = "#e68483"
    LIGHT_BLUE = "#bec8f4"
    LIGHT_PURPLE = "#c8a7f7"
    LIGHT_GREY = "#aaaaaa"


class NodeType(Enum):
    MDL = 1  # TODO: maybe we can promote MDL to some general 'source asset' type node?
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
    NodeType.UNKNOWN: UIColors.LIGHT_GREY,
}


def MakeBorderWidgetStyle(
    backgroundColor: str = UIColors.CHARCOAL.value,
) -> str:
    return f"""
        QWidget#ThisWidget {{
            background-color: {backgroundColor};
            border-color: #000;
            border-width: 1px;
            border-style: inset;
        }}
    """


BORDER_WIDGET_STYLE = MakeBorderWidgetStyle()


def MakeNodeBackgroundStyle(backgroundColor: str) -> str:
    return f"""
        QWidget#NodeBackground {{
            background-color: {backgroundColor};
        }}
    """


# Connections and their port markers share this color.
SPLINE_COLOR = "#ffffff"

# Default colors for the customizable graph elements.
DEFAULT_NODE_COLORS = {
    NodeType.USDA.name: UIColors.GOLD.value,
    NodeType.MDL.name: UIColors.MDL_GREEN.value,
    NodeType.MTLX.name: UIColors.LIGHT_RED.value,
    NodeType.OSL.name: UIColors.LIGHT_BLUE.value,
    NodeType.NODE_GRAPH.name: UIColors.LIGHT_PURPLE.value,
    NodeType.UNKNOWN.name: UIColors.LIGHT_GREY.value,
}


def _NormalizeColor(value: str) -> str:
    """Normalizes color strings so equivalent colors compare as equal."""
    return value.lower() if isinstance(value, str) else value


@dataclass
class GraphColors:
    """User-configurable colors used to draw the node graph."""

    nodeColors: dict[str, str] = field(
        default_factory=lambda: dict(DEFAULT_NODE_COLORS)
    )
    connectionColor: str = SPLINE_COLOR
    backgroundColor: str = UIColors.CHARCOAL.value
    gridColor: str = UIColors.DARK_GREY.value
    nodeBackgroundColor: str = UIColors.CHARCOAL.value

    def __post_init__(self):
        self.nodeColors = {
            key: _NormalizeColor(value)
            for key, value in self.nodeColors.items()
        }
        self.connectionColor = _NormalizeColor(self.connectionColor)
        self.backgroundColor = _NormalizeColor(self.backgroundColor)
        self.gridColor = _NormalizeColor(self.gridColor)
        self.nodeBackgroundColor = _NormalizeColor(self.nodeBackgroundColor)

    def GetNodeColor(self, nodeType: NodeType) -> str:
        """Returns the header color for the given node type."""
        key = nodeType.name
        if key not in self.nodeColors:
            key = NodeType.NODE_GRAPH.name
        return self.nodeColors.get(key, UIColors.LIGHT_GREY.value)

    def ToDict(self) -> dict:
        """Serializes the colors to a JSON-compatible dictionary."""
        return {
            "nodeColors": dict(self.nodeColors),
            "connectionColor": self.connectionColor,
            "backgroundColor": self.backgroundColor,
            "gridColor": self.gridColor,
            "nodeBackgroundColor": self.nodeBackgroundColor,
        }

    @classmethod
    def FromDict(cls, data) -> GraphColors:
        """Restores colors from a dictionary, ignoring invalid entries."""
        colors = cls()
        if not isinstance(data, dict):
            return colors

        nodeColors = data.get("nodeColors")
        if isinstance(nodeColors, dict):
            for key in colors.nodeColors:
                value = nodeColors.get(key)
                if isinstance(value, str):
                    colors.nodeColors[key] = _NormalizeColor(value)

        for key in (
            "connectionColor",
            "backgroundColor",
            "gridColor",
            "nodeBackgroundColor",
        ):
            value = data.get(key)
            if isinstance(value, str):
                setattr(colors, key, _NormalizeColor(value))

        return colors


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
