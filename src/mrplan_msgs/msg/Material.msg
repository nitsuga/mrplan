std_msgs/Header header       # Message header
uint8 type
uint8 RED             = 0 # Red materials only appear during certain time windows
uint8 BLUE            = 1 # Blue materials take a long time to collect
uint8 GREEN           = 2 # Green materials require two robots to collect
uint8 WHITE           = 3 # White materials have a limited 'shelf life' once collected
uint8 BLACK           = 4 # Only 1 black material can be held at once

