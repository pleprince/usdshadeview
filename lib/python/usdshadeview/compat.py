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

"""Qt binding and optional dependency detection."""

import os

from pxr.Usdviewq.qt import GetPySideModule

PySideModule = GetPySideModule()

if PySideModule == 'PySide2':
    # There is an issue on Windows where under certain circumstances the
    # buttons in the QGraphicsView cannot be clicked anymore. There's also
    # some error log spam. This might not affect all OSes.
    enableHwAcceleration = False
else:
    # Disable this if you run into rendering issues
    enableHwAcceleration = (
        os.getenv("USDSHADEVIEW_HW_ACCEL", "1")
        in ("1", "true", "yes", "on"))

mtlxSupported = True
try:
    from pxr import UsdBakeMtlx
except ModuleNotFoundError:
    UsdBakeMtlx = None
    mtlxSupported = False

# Allows us to support EXR and other image file types that Qt doesn't
try:
    import OpenImageIO as oiio
except ModuleNotFoundError:
    oiio = None

oiioSupported = oiio is not None and hasattr(oiio, 'ImageInput')
