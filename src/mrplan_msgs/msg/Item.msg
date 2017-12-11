string item_id       # Unique task identifier
Material[]           # 
string[] depends     # Ids of other tasks that must be completed first

uint8 num_robots     # Number of robots needed to complete this task
float32 duration     # Time (in seconds) required to 'execute' the task
float32 arrival_time # Time (in seconds) at which the task 'arrives'
                     # after start of experiment