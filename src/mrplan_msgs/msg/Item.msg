string item_id       # Unique item identifier

uint8 GREY            = 0 # A colourless, generic material with no special properties
uint8 RED             = 1 # Red materials only appear during certain time windows
uint8 BLUE            = 2 # Blue materials take a long time to collect
uint8 GREEN           = 3 # Green materials require two robots to collect
uint8 WHITE           = 4 # White materials have a limited 'shelf life' once collected
uint8 BLACK           = 5 # Only 1 black material can be held at once

uint8 material_count[]    # The number of each type of material required by this item.
                          # Indexes are material types (e.g., material_count[Item.RED] = 1

string site               # Location (waypoint) where the item should be constructed/delivered

