#### ItemBid.msg
# A bid for an Item computed and submitted by a robot

string item_id         # The ID of the item to bid on
string robot_id        # Unique id/name of the bidding robot

# The total distance that must be travelled to construct all items
# in the robot's agenda, including the item under consideration
float64 total_distance_cost

# The additional distance a robot must travel to construct the item
# under consideration, if that item were inserted into the robot's agenda.
float64 marginal_distance_cost

# The total time taken to construct all items in the robot's agenda,
# including the item under consideration
float64 total_time_cost

# The additional time taken to construct the item under consideration,
# if that item were inserted into the robot's agenda.
float64 marginal_time_cost


