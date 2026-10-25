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

"""Prim context menu integration."""

from pxr import UsdShade
from pxr.Usdviewq.primContextMenuItems import PrimContextMenuItem


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
