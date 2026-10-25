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

"""Small helpers shared across the plugin."""

import os
import platform
import shutil
import subprocess

from pxr import Sdr, Usd, UsdShade

from .constants import NodeType


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
