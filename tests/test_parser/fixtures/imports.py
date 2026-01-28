"""Sample Python file with various import patterns for testing."""

# Simple imports
import os
import sys
import json

# Dotted imports
import os.path
import collections.abc

# Aliased imports
import numpy as np
import pandas as pd

# From imports
from pathlib import Path
from typing import List, Dict, Optional

# From import with alias
from collections import OrderedDict as OD
from typing import Union as U

# Relative imports (for syntax only - won't actually work)
from . import sibling
from ..parent import something
from ...grandparent.module import item

# Wildcard import
from os.path import *
