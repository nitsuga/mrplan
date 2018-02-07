"""item.py

This module defines the Item class used in MRPlan experiments.

Eric Schneider <eric.schneider@liverpool.ac.uk>
"""

from enum import Enum


class Material(Enum):
    """ Materials are composed to make up Items. At first, this class
    just identifies and distinguishes one material from another via an
    enumeration pattern. In future, this class may implement material
    properties as described in mrplan_msgs/msg/Item.msg
    """
    GREY = 0
    RED = 1
    BLUE = 2
    GREEN = 3
    WHITE = 4
    BLACK = 5


class Item(object):

    def __init__(self, _item_id='1', _materials=[0, 0, 0, 0, 0, 0], _site=''):

        # A unique identifier for this item.
        self.item_id = _item_id

        # The numbers of each type of material needed to construct
        # this Item. An index of this list represents a Material type
        # (an enumeration, above) with an integer values that represents
        # the number of units of that material required.
        self.materials = _materials

        self.site = _site

        self.completed = False
        self.awarded = False


