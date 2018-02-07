#!/usr/bin/env python

"""mrta_auctioneer

This program serves as the task-allocating agent in a multirobot system. It is
responsible for:

  1. Loading a group of tasks that make up a "mission". These tasks may have
     dependencies among them (e.g., ordering), real-time constraints (e.g.,
     deadlines or windows), or other constraints. By "loading", we mean that
     tasks are read from a task- or mission-definition file at startup, received
     online from a mission-controlling agent (e.g., a person operating a GUI).

  2. Announcing tasks (in a particular order, if constrained) to team members.
     Tasks may be announced in groups, or "bundles".

  3. Receiving bids on tasks from team members. A bid is a real numbered value
     that (for now) represents the cost that a team member estimates it will
     incur to complete the task. For example, the distance it will need to
     travel to reach a certain point in the world.

  4. Determining the "winner" of every task. A winner is usually the team
     member that submitted the lowest bid.

The term "mechanism" refers to the way in which tasks are announced, bids collected,
and tasks are awarded. Depending on the mechanism, the announcement and bid collection
phases may be skipped (e.g., in a round-robin mechanism).

Usage: auctioneer.py ['RR'|'PSI'|'OSI'|'SSI'] [path to task definition file]

  The first argument specifies the mechanism to use. These abbreviations stand for
  "round robin", "parallel single-item", "ordered single-item", and "sequential
  single-item", respectively. These mechanisms are explained in [1].

  The second argument gives the path to a file whose contents specify the
  set of tasks that make up a mission. The format of this file is explained
  in [TODO].


Eric Schneider <eric.schneider@liverpool.ac.uk>

[1] Schneider, Balas, et al. 2014. An empirical evaluation of auction-based task allocation in multi-robot teams. In Proceedings of the 2014 international conference on Autonomous agents and multi-agent systems (AAMAS '14).
"""

# Standard Python modules
from collections import defaultdict
import itertools
import numpy as np
import os
from partitionsets import ordered_set, partition
import pickle
import pprint
import re
import scipy.spatial
from sets import Set
import signal
import sys
from threading import Timer, Lock
import time
import uuid
import yaml

# igraph library
import igraph

# Fysom state machine
from fysom import Fysom

# ROS modules
# import actionlib
from collections import defaultdict
import geometry_msgs.msg
from itertools import chain, combinations
# import move_base_msgs.msg
# import nav_msgs.msg
# import rosgraph
# import rosgraph.names
import rosnode
import rospkg
import rospy
import rospy.rostime
import visualization_msgs.msg

# MRPlan-specific modules
import mrplan_msgs.msg
from mrplan_auctioneer.item import Item

# p-median -finding libraries
from p_median import pmed_greedy
from p_median import teitz_bart

# We'll sleep 1/RATE seconds in every pass of the idle loop.
RATE = 10

pp = pprint.PrettyPrinter(indent=2)


ROBOT_COLORS = {'robot_1': [1.0, 0.0, 0.0],
                'robot_2': [0.0, 1.0, 0.0],
                'robot_3': [0.0, 0.0, 1.0]}


def on_sigint(signal):
    print('Caught SIGINT, shutting down...')
    sys.exit(0)


def stamp(msg):
    """ Set the timestamp of a message to the current wall-clock time."""
    rospy.rostime.switch_to_wallclock()
    msg.header.stamp = rospy.rostime.get_rostime()


def powerset(iterable):
    """
    powerset([1,2,3]) --> () (1,) (2,) (3,) (1,2) (1,3) (2,3) (1,2,3)

    Shamelessly taken from:
      https://docs.python.org/2/library/itertools.html#recipes

    :param iterable:
    :return:
    """
    s = list(iterable)
    return chain.from_iterable(combinations(s, r) for r in range(len(s) + 1))


class Auction(object):
    def __init__(self, auctioneer=None, items=None, auction_round=None):
        
        # A handle to the Auctioneer object who called us
        self.auctioneer = auctioneer

        # The tasks we are meant to announce/award in the current round
        self.items = items

        # To identify in which round bids are made for tasks
        self.auction_round = auction_round

        # Set up state machine.
        # See multirobot/docs/auctioneer-fsm.png
        self.fsm = Fysom( 
            events=[
                ('startup', 'none', 'announce'),
                ('announced', 'announce', 'collect_bids'),
                ('bids_collected', 'collect_bids', 'determine_winner'),
                ('winner_determined', 'determine_winner', 'award'),
            ],
            callbacks={
                # on-enter state handlers
                'onannounce': self.announce,
                'oncollect_bids': self.collect_bids,
                'ondetermine_winner': self.determine_winner,
                'onaward': self.award
            }
        )

        # Start the state machine
        self.fsm.startup()

    def _construct_task_msg(self, task):
        """
        Maps from our internal task representation to a ROS message type.
        (mrta.SensorSweepTask => mrta.msg.SensorSweepTask)
        """
        # Just sensor sweep tasks for now
        task_msg = mrta.msg.SensorSweepTask()

        task_msg.task.task_id = task.task_id
        task_msg.task.depends = task.depends
        task_msg.task.type = task.type
        task_msg.task.num_robots = task.num_robots
        task_msg.task.duration = task.duration
        task_msg.location.x = task.location.x
        task_msg.location.y = task.location.y
        task_msg.location.z = task.location.z

        return task_msg

    def _construct_item_msg(self, item):
        """
        Maps from our internal item representation to a ROS message type.
        (mrplan_auctioneer.item.Item => mrplan_msgs.msg.Item)
        """
        # Just sensor sweep tasks for now
        item_msg = mrplan_msgs.msg.Item()

        item_msg.item_id = item.item_id
        item_msg.material_count = item.materials
        item_msg.site = item.site

        return item_msg

    def _construct_announcement_msg(self):
        pass

    def _get_item_by_id(self, item_id):
        return self.auctioneer.item_by_id[item_id]

    def announce(self, e):
        pass

    def collect_bids(self, e):
        """
        Here, we can either wait for a time limit (deadline) to pass or,
        knowing the size of the team and the mechanism being used, we can
        calculate how many bids we expect to receive before we consider
        the bid collection phase finished.

        Before the time limit passes, we expect to receive bid messages, which
        will trigger Auctioneer.on_bid_received().
        """
        pass
            
    def determine_winner(self, e):
        pass

    def award(self, e):
        pass


class AuctionOSI(Auction):

    mechanism_name = 'OSI'

    def __init__(self, auctioneer=None, items=None, auction_round=None):
        super(AuctionOSI, self).__init__(auctioneer, items, auction_round)

    def _construct_announcement_msg(self):
        # announce_msg = mrta.msg.AnnounceSensorSweep()
        # announce_msg.mechanism = self.mechanism_name
        #
        # # Only announce one task (the first in the auctioneer's list)
        # announce_msg.tasks.append(self._construct_task_msg(self.tasks[0]))
        #
        # return announce_msg
        return self._construct_item_msg(self.items[0])

    def announce(self, e):
        rospy.loginfo("({0}) state: announce".format(self.mechanism_name))

        while not self.auctioneer.team_members:
            rospy.logdebug("..waiting for team to be non-empty")
            time.sleep(1)
        
        announcement_msg = self._construct_announcement_msg()
        stamp(announcement_msg)
        self.auctioneer.announce_pub.publish(announcement_msg)

        rospy.loginfo("announce_pub:\n{0}".format(pp.pformat(self.auctioneer.announce_pub)))
        rospy.loginfo("Announcement:\n{0}".format(pp.pformat(announcement_msg)))

        self.fsm.announced()

    def collect_bids(self, e):
        rospy.loginfo("({0}) state: collect_bids".format(self.mechanism_name))

        bids = self.auctioneer.bids[self.auction_round]

        # In OSI, we wait to receive as many bids as there are team members
        while len(bids) < len(self.auctioneer.team_members):
            # time.sleep(0.2)
            self.auctioneer.rate.sleep()

        self.fsm.bids_collected(task_id=self.tasks[0].task_id)

    def determine_winner(self, e):
        rospy.loginfo("({0}) state: determine_winner".format(self.mechanism_name))

        # The id and task that we are assigning in this round
        task_id = e.task_id
        task = self._get_task_by_id(task_id)

        bids = self.auctioneer.bids[self.auction_round]
        bid_tuples = []
        for robot_id in bids.keys():
            if robot_id not in self.auctioneer.awarded[task_id]:
                # task_id below is a 1-tuple. see Auctioneer.on_bid_received()
                bid_tuples.append([robot_id, bids[robot_id][tuple([task_id])]]) # i.e., [robot_id, bid_value]

        # Sort tuples of [robot_id],[bid_value] in ascending order of bid value
        bid_tuples = sorted(bid_tuples, key=lambda entry: entry[1])

        # Award the 'num_robots' lowest bidders per round (i.e.,
        # bid_tuples[:num_robots] rather than bid_tuples[0])
        num_robots = task.num_robots
        winner_ids = map(lambda entry: entry[0], bid_tuples[:num_robots])
#        winner_ids = map(lambda entry: entry[0], bid_tuples[:1])

        self.auctioneer.awarded[task_id].extend(winner_ids)

        rospy.loginfo("winner(s) of task {0}: '{1}'".format(task_id, winner_ids))

        self.fsm.winner_determined(task_id=task_id, winner_ids=winner_ids)

    def award(self, e):
        """ Construct and send an award message. """
        rospy.loginfo("({0}) state: award".format(self.mechanism_name))

        won_task = self._get_task_by_id(e.task_id)

        winner_ids = e.winner_ids

        for winner_id in winner_ids:
            award_msg = mrta.msg.TaskAward()
            award_msg.robot_id = winner_id
            task_msg = self._construct_task_msg(won_task)
            award_msg.tasks.append(task_msg)

            stamp(award_msg)
            self.auctioneer.award_pub.publish(award_msg)

            # Remove/republish task marker with winning robot's color
            self.auctioneer.remove_task_marker(won_task.task_id)
            self.auctioneer.publish_task_marker(won_task, ROBOT_COLORS[winner_id])

            won_task.num_robots_allocated += 1

        # Mark the task as awarded if the task has been awarded to its required
        # number of robots
        if won_task.num_robots_allocated == won_task.num_robots:
            won_task.awarded = True

        time.sleep(0.5)


class AuctionPSI(Auction):
    """ A Parallel Single-Item auction.

    See:
    Koenig, Sven, et al. "The power of sequential single-item auctions for agent
    coordination." Proceedings of the National Conference on Artificial
    Intelligence. Vol. 21. No. 2. Menlo Park, CA; Cambridge, MA; London; AAAI
    Press; MIT Press; 1999, 2006.
    """
    mechanism_name = 'PSI'

    def __init__(self, auctioneer=None, tasks=None, auction_round=None):
        super(AuctionPSI, self).__init__(auctioneer, tasks, auction_round)

    def _construct_announcement_msg(self):
        announce_msg = mrta.msg.AnnounceSensorSweep()
        announce_msg.mechanism = self.mechanism_name

        # Announce all messages at once
        for task in self.tasks:
            announce_msg.tasks.append(self._construct_task_msg(task))

        return announce_msg

    def announce(self, e):
        rospy.loginfo("({0}) state: announce".format(self.mechanism_name))

        while not self.auctioneer.team_members:
            rospy.logdebug("..waiting for team to be non-empty")
            time.sleep(1)

        announcement_msg = self._construct_announcement_msg()
        stamp(announcement_msg)
        self.auctioneer.announce_pub.publish(announcement_msg)

        rospy.logdebug("Announcement:\n{0}".format(pp.pformat(announcement_msg)))

        self.fsm.announced()

    def collect_bids(self, e):
        rospy.loginfo("({0}) state: collect_bids".format(self.mechanism_name))

        bids = self.auctioneer.bids[self.auction_round]

        # In PSI, the number of bids we expect to receive is [#tasks]*[team size]
        bid_count = 0
        while bid_count < len(self.tasks) * len(self.auctioneer.team_members):
            bid_count = 0
            for robot_id in bids:
                for task_id in bids[robot_id]:
                    bid_count += 1

            # time.sleep(0.2)
            self.auctioneer.rate.sleep()

        rospy.logdebug("({0}) received {1} bids, moving to determine_winner".format(self.mechanism_name, bid_count))

        self.fsm.bids_collected()

    def determine_winner(self, e):
        rospy.loginfo("({0}) state: determine_winner".format(self.mechanism_name))
        
        bids = self.auctioneer.bids[self.auction_round]

        rospy.logdebug("bids:\n{0}".format(pp.pformat(bids)))

        # We'll determine the winner of and send an award message for each task
        task_winners = defaultdict(list) # task_winners[task_id] = [winner_ids]

        for task in self.tasks:

            bid_tuples = []
            for robot_id in bids.keys():
                if robot_id not in self.auctioneer.awarded[task.task_id]:
                    # task_id below is a 1-tuple. see Auctioneer.on_bid_received()
                    rospy.loginfo("Reading bid from {0} for {1}".format(robot_id, task.task_id))
                    try:
                        bid_tuples.append([robot_id, bids[robot_id][tuple([task.task_id])]]) # i.e., [robot_id, bid_value]
                    except KeyError:
                        pp.pprint(bid_tuples)

            # Sort tuples of [robot_id],[bid_value] in ascending order of bid value
            bid_tuples = sorted(bid_tuples, key=lambda entry: entry[1])

            num_robots = task.num_robots
            # The top (actually lowest) num_robots bids
            winner_ids = map(lambda entry: entry[0], bid_tuples[:num_robots])

            self.auctioneer.awarded[task.task_id].extend(winner_ids)

            rospy.loginfo("winner(s) of task {0}: '{1}'".format(task.task_id, winner_ids))

            task_winners[task.task_id] = winner_ids

        self.fsm.winner_determined(task_winners=task_winners)

    def award(self, e):
        """ Construct and send an award message for each winner. """
        rospy.loginfo("({0}) state: award".format(self.mechanism_name))

        task_winners = e.task_winners

        for task_id in task_winners:
            won_task = self._get_task_by_id(task_id)

            for winner_id in task_winners[task_id]:

                award_msg = mrta.msg.TaskAward()
                award_msg.robot_id = winner_id

                task_msg = self._construct_task_msg(won_task)
                award_msg.tasks.append(task_msg)

                self.auctioneer.award_pub.publish(award_msg)

                rospy.logdebug("sending award message:\n{0}".format(pp.pformat(award_msg)))

                # Remove/republish task marker with winning robot's color
                self.auctioneer.remove_task_marker(won_task.task_id)
                self.auctioneer.publish_task_marker(won_task, ROBOT_COLORS[winner_id])

            # Mark the task as awarded
            won_task.awarded = True


class AuctionPPSI(AuctionPSI):

    mechanism_name = 'PPSI'

    def __init__(self, auctioneer=None, tasks=None, auction_round=None):
        # A handle to the Auctioneer object who called us
        self.auctioneer = auctioneer

        # The tasks we are meant to announce/award in the current round
        self.tasks = tasks

        # To identify in which round bids are made for tasks
        self.auction_round = auction_round

        # Set up state machine.
        # See multirobot/docs/auctioneer-fsm.png

        # This is essentially the same as PSI, except we remove the
        # transition from determine_winner to award. In PPSI, determin_winner
        # will return the dict task_winners so that the caller can decide
        # what to do.

        self.fsm = Fysom(
            events=[
                ('startup', 'none', 'announce'),
                ('announced', 'announce', 'collect_bids'),
                ('bids_collected', 'collect_bids', 'determine_winner'),
            ],
            callbacks={
                # on-enter state handlers
                'onannounce': self.announce,
                'oncollect_bids': self.collect_bids,
                'ondetermine_winner': self.determine_winner,
            }
        )

        # Start the state machine
        self.fsm.startup()

    def determine_winner(self, e):
        rospy.loginfo("({0}) state: determine_winner".format(self.mechanism_name))

        bids = self.auctioneer.bids[self.auction_round]

        rospy.logdebug("bids:\n{0}".format(pp.pformat(bids)))

        # We'll determine the winner of and send an award message for each task
        task_winners = defaultdict(list)  # task_winners[task_id] = [winner_ids]

        for task in self.tasks:

            bid_tuples = []
            for robot_id in bids.keys():
                if robot_id not in self.auctioneer.awarded[task.task_id]:
                    # task_id below is a 1-tuple. see Auctioneer.on_bid_received()
                    rospy.loginfo("Reading bid from {0} for {1}".format(robot_id, task.task_id))
                    try:
                        bid_tuples.append([robot_id, bids[robot_id][tuple([task.task_id])]])  # i.e., [robot_id, bid_value]
                    except KeyError:
                        pp.pprint(bid_tuples)

            # Sort tuples of [robot_id],[bid_value] in ascending order of bid value
            bid_tuples = sorted(bid_tuples, key=lambda entry: entry[1])

            num_robots = task.num_robots
            # The top (actually lowest) num_robots bids
            winner_ids = map(lambda entry: entry[0], bid_tuples[:num_robots])

            # self.auctioneer.awarded[task.task_id].extend(winner_ids)

            rospy.loginfo("winner(s) of task {0}: '{1}'".format(task.task_id, winner_ids))

            task_winners[task.task_id] = winner_ids

        self.auctioneer.ppsi_task_winners = task_winners


class AuctionSSI(Auction):
    """ A Sequential Single-Item auction.

    See:
    Koenig, Sven, et al. "The power of sequential single-item auctions for agent
    coordination." Proceedings of the National Conference on Artificial
    Intelligence. Vol. 21. No. 2. Menlo Park, CA; Cambridge, MA; London; AAAI
    Press; MIT Press; 1999, 2006.
    """
    mechanism_name = 'SSI'

    def __init__(self, auctioneer=None, tasks=None, auction_round=None):
        super(AuctionSSI, self).__init__(auctioneer, tasks, auction_round)

    def _construct_announcement_msg(self):
        announce_msg = mrta.msg.AnnounceSensorSweep()
        announce_msg.mechanism = self.mechanism_name

        # Announce all messages at once
        for task in self.tasks:
            announce_msg.tasks.append(self._construct_task_msg(task))

        return announce_msg

    def announce(self, e):
        rospy.loginfo("({0}) state: announce".format(self.mechanism_name))

        while not self.auctioneer.team_members:
            rospy.logdebug("..waiting for team to be non-empty")
            time.sleep(1)

        announcement_msg = self._construct_announcement_msg()
        stamp(announcement_msg)
        self.auctioneer.announce_pub.publish(announcement_msg)

        rospy.loginfo("Announcement:\n{0}".format(pp.pformat(announcement_msg)))

        self.fsm.announced()

    def collect_bids(self, e):
        rospy.loginfo("({0}) state: collect_bids".format(self.mechanism_name))

        bids = self.auctioneer.bids[self.auction_round]

        # In SSI, we wait to receive as many bids as there are team members
        while len(bids) < len(self.auctioneer.team_members):
            time.sleep(0.1)

        self.fsm.bids_collected()

    def determine_winner(self, e):
        rospy.loginfo("({0}) state: determine_winner".format(self.mechanism_name))

        bids = self.auctioneer.bids[self.auction_round]
        bid_tuples = []
        for robot_id in bids:
            # task_ids below is a 1-tuple. see Auctioneer.on_bid_received()
            for task_ids in bids[robot_id]:
                if robot_id not in self.auctioneer.awarded[task_ids[0]]:
                    bid_tuples.append([robot_id, task_ids[0], bids[robot_id][tuple(task_ids)]]) # i.e., [robot_id, task_id, bid_value]

        # Sort tuples of [robot_id],[bid_value] in ascending order of bid value
        bid_tuples = sorted(bid_tuples, key=lambda entry: entry[2])

        rospy.loginfo("bid_tuples: {0}".format(pp.pformat(bid_tuples)))

        # For now, award the single lowest bidder. But we may want to award the 'num_robots' lowest bidders
        # per round (i.e., bid_tuples[:num_robots] rather than bid_tuples[0] for the minimum-bid task, below)
        # num_robots = self._get_task_by_id(bid_tuples[0][1]).num_robots
        # winner_ids = map(lambda entry: entry[0], bid_tuples[:num_robots])
        winner_ids = map(lambda entry: entry[0], bid_tuples[:1])
        winning_task_id = bid_tuples[0][1]

        self.auctioneer.awarded[winning_task_id].extend(winner_ids)

        rospy.loginfo("winner(s) of task {0}: '{1}'".format(winning_task_id, winner_ids))

        self.fsm.winner_determined(task_id=winning_task_id, winner_ids=winner_ids)

    def award(self, e):
        """ Construct and send an award message. """
        rospy.loginfo("({0}) state: award".format(self.mechanism_name))

        won_task = self._get_task_by_id(e.task_id)

        winner_ids = e.winner_ids

        for winner_id in winner_ids:
            award_msg = mrta.msg.TaskAward()
            award_msg.robot_id = winner_id
            task_msg = self._construct_task_msg(won_task)
            award_msg.tasks.append(task_msg)

            stamp(award_msg)
            self.auctioneer.award_pub.publish(award_msg)

            # Remove/republish task marker with winning robot's color
            self.auctioneer.remove_task_marker(won_task.task_id)
            self.auctioneer.publish_task_marker(won_task, ROBOT_COLORS[winner_id])

            won_task.num_robots_allocated += 1

        # Mark the task as awarded if the task has been awarded to its required
        # number of robots
        if won_task.num_robots_allocated == won_task.num_robots:
            won_task.awarded = True

        time.sleep(0.5)


class AuctionRR(Auction):
    """
    A round-robin auction
    """
    mechanism_name = 'RR'

    def __init__(self, auctioneer=None, tasks=None, auction_round=None):
        super(AuctionRR, self).__init__(auctioneer, tasks, auction_round)

    def _construct_announcement_msg(self):
        announce_msg = mrta.msg.AnnounceSensorSweep()
        announce_msg.mechanism = self.mechanism_name

        # Only announce one task (the first in the auctioneer's list)
        announce_msg.tasks.append(self._construct_task_msg(self.tasks[0]))

        return announce_msg

    def announce(self, e):
        rospy.loginfo("({0}) state: announce".format(self.mechanism_name))
        rospy.loginfo("..skipping!")

        self.fsm.announced()

    def collect_bids(self, e):
        rospy.loginfo("({0}) state: collect_bids".format(self.mechanism_name))
        rospy.loginfo("..skipping!")

        self.fsm.bids_collected()

    def determine_winner(self, e):
        rospy.loginfo("({0}) state: determine_winner".format(self.mechanism_name))
        rospy.loginfo("..skipping!")

        self.fsm.winner_determined()

    def award(self, e):
        """ Construct and send an award message for each task. """
        rospy.loginfo("({0}) state: award".format(self.mechanism_name))

        # A cycling iterator of team member names
        # team_cycle = itertools.cycle(self.auctioneer.team_members)

        for task in self.tasks:

            while not task.awarded:

                award_msg = mrta.msg.TaskAward()

                # award_msg.robot_id = team_cycle.next()
                award_msg.robot_id = self.auctioneer._team_cycle.next()

                task_msg = self._construct_task_msg(task)
                award_msg.tasks.append(task_msg)

                rospy.logdebug("sending award message:\n{0}".format(pp.pformat(award_msg)))

                stamp(award_msg)
                self.auctioneer.award_pub.publish(award_msg)

                # Remove/republish task marker with winning robot's color
                self.auctioneer.remove_task_marker(task.task_id)
                self.auctioneer.publish_task_marker(task, ROBOT_COLORS[award_msg.robot_id])

                task.num_robots_allocated += 1

                # Mark the task as awarded if the task has been awarded to its required
                # number of robots
                if task.num_robots_allocated == task.num_robots:
                    task.awarded = True


class AuctionSUM(Auction):
    """
    A combinatorial auction that minimizes the maximum sum of travel distances
    for the team as a whole.
    """
    mechanism_name = 'SUM'

    def __init__(self, auctioneer=None, tasks=None, auction_round=None):
        super(AuctionSUM, self).__init__(auctioneer, tasks, auction_round)

    def _min_bid_for_round(self, tasks, round, robot_cost):
        """
        Return the minimum bid (value) and robot_id for a given set of tasks
        :param tasks: a *tuple* of task_ids
        :param round: search bids from this auction round
        :param robot_cost: a dict of the costs robots have already accumulated in this round
        :return: a tuple of <minimum bid>, <minimum bid robot_id>
        """
        min_bid = None
        min_robot_id = None

        bids = self.auctioneer.bids[round]

        for robot_id in bids.keys():
            # Get the robot's bid for the given tasks. If there is none,
            # default to a 'very large' value (as in mrta.RobotController.bid())
            bid_value = bids[robot_id].get(tasks, float(sys.maxint))

            cum_cost = robot_cost[robot_id]

            if min_bid is None or (bid_value + cum_cost) < min_bid:
                min_bid = bid_value + cum_cost
                min_robot_id = robot_id

        # rospy.loginfo("({0}) min_bid for {1}: {2} by {3}".format(self.mechanism_name,
        #                                                          pp.pformat(tasks),
        #                                                          min_bid,
        #                                                          min_robot_id))
        return min_bid, min_robot_id

    def _construct_announcement_msg(self):
        """
        We announce all tasks in a single set, as in PSI
        :return: An mrta.msg.AnnounceSensorSweep message
        """
        announce_msg = mrta.msg.AnnounceSensorSweep()
        announce_msg.mechanism = self.mechanism_name

        # Announce all messages at once
        for task in self.tasks:
            announce_msg.tasks.append(self._construct_task_msg(task))

        return announce_msg

    def announce(self, e):
        rospy.loginfo("({0}) state: announce".format(self.mechanism_name))

        while not self.auctioneer.team_members:
            rospy.logdebug("..waiting for team to be non-empty")
            time.sleep(1)

        announcement_msg = self._construct_announcement_msg()
        stamp(announcement_msg)
        self.auctioneer.announce_pub.publish(announcement_msg)

        rospy.logdebug("Announcement:\n{0}".format(pp.pformat(announcement_msg)))

        self.fsm.announced()

    def collect_bids(self, e):
        rospy.loginfo("({0}) state: collect_bids".format(self.mechanism_name))

        bids = self.auctioneer.bids[self.auction_round]

        # For n tasks and m robots, the number of bids we expect to receive is:
        #  (2^n - 1) * m
        #  (|the powerset of tasks| minus the empty set) * m
        expected_count = (2 ** len(self.tasks) - 1) * len(self.auctioneer.team_members)

        bid_count = 0
        while bid_count < expected_count:
            self.auctioneer.bids_lock.acquire()

            try:
                bid_count = 0
                for robot_id in bids:
                    for task_tuple in bids[robot_id]:
                        bid_count += 1
            finally:
                self.auctioneer.bids_lock.release()

            rospy.loginfo('Received [{0}/{1}] bids...'.format(bid_count, expected_count))
            self.auctioneer.rate.sleep()

        self.fsm.bids_collected()

    def determine_winner(self, e):
        rospy.loginfo("({0}) state: determine_winner".format(self.mechanism_name))

        # 1. Create an OrderedSet set of task_ids
        tasks_oset = ordered_set.OrderedSet([t.task_id for t in self.tasks])

        # 2. Get a list of all possible partitions of the set
        t_partitions = partition.Partition(tasks_oset)

        # 3. For each partition, find the min-cost combination of bids
        min_cost = float(sys.maxint)   # A 'very large' value, to start with
        min_cost_partition = None     # A dict of (task set) => ([bid_value, robot_id])

        for t_partition in t_partitions:

            mincost_dict = defaultdict(list)

            robot_cost = defaultdict(float)

            # Each partition is a list of lists (of tasks)
            for t_list in t_partition:
                t_tuple = tuple(t_list)
                # rospy.loginfo("({0}) t_set: {1}".format(self.mechanism_name, pp.pformat(t_tuple)))

                min_bid, min_robot_id = self._min_bid_for_round(t_tuple, self.auction_round, robot_cost)

                mincost_dict[t_tuple] = [min_bid, min_robot_id]
                robot_cost[min_robot_id] += min_bid

            partition_cost = sum(v[0] for v in mincost_dict.values())

            assn_str = ["{0} => {1} ".format(t, mincost_dict[t][1]) for t in mincost_dict]
            rospy.logdebug("partition cost: {0} for {1}".format(partition_cost, assn_str))

            if not min_cost_partition or partition_cost < min_cost:
                min_cost = partition_cost
                min_cost_partition = mincost_dict
                rospy.loginfo("min partition cost: {0}".format(partition_cost))
                rospy.loginfo("assignment: {0}".format(assn_str))

        # Done?
        self.fsm.winner_determined(min_cost_partition=min_cost_partition)

    def award(self, e):
        """ Construct and send an award message for each winner. """
        rospy.loginfo("({0}) state: award".format(self.mechanism_name))

        min_cost_partition = e.min_cost_partition

        for t_subset in min_cost_partition.keys():
            # t_subset is a *tuple* of task_ids
            [bid_value, robot_id] = min_cost_partition[t_subset]

            award_msg = mrta.msg.TaskAward()
            award_msg.robot_id = robot_id

            for task_id in t_subset:
                won_task = self._get_task_by_id(task_id)

                won_task.num_robots_allocated += 1
                if won_task.num_robots_allocated == won_task.num_robots:
                    won_task.awarded = True

                award_msg.tasks.append(self._construct_task_msg(won_task))

            self.auctioneer.award_pub.publish(award_msg)

            rospy.logdebug("sending award message:\n{0}".format(pp.pformat(award_msg)))
            time.sleep(1)


class AuctionMAX(Auction):
    """
    A combinatorial auction that minimizes the maximum travel distance of any
    single robot on the team.
    """
    mechanism_name = 'MAX'

    def __init__(self, auctioneer=None, tasks=None, auction_round=None):
        super(AuctionMAX, self).__init__(auctioneer, tasks, auction_round)

    def _min_bid_for_round(self, tasks, round, robot_cost):
        """
        Return the minimum bid (value) and robot_id for a given set of tasks
        :param tasks: a *tuple* of task_ids
        :param round: search bids from this auction round
        :param robot_cost: a dict of the costs robots have already accumulated in this round
        :return: a tuple of <minimum bid>, <minimum bid robot_id>
        """
        min_bid = None
        min_robot_id = None

        bids = self.auctioneer.bids[round]

        for robot_id in bids.keys():
            # Get the robot's bid for the given tasks. If there is none,
            # default to a 'very large' value (as in mrta.RobotController.bid())
            bid_value = bids[robot_id].get(tasks, float(sys.maxint))

            cum_cost = robot_cost[robot_id]

            # if min_bid is None or bid_value < min_bid:
            if min_bid is None or (bid_value + cum_cost) < min_bid:
                min_bid = bid_value + cum_cost
                min_robot_id = robot_id

        # rospy.loginfo("({0}) min_bid for {1}: {2} by {3}".format(self.mechanism_name,
        #                                                          pp.pformat(tasks),
        #                                                          min_bid,
        #                                                          min_robot_id))
        return min_bid, min_robot_id

    def _construct_announcement_msg(self):
        """
        We announce all tasks in a single set, as in PSI
        :return: An mrta.msg.AnnounceSensorSweep message
        """
        announce_msg = mrta.msg.AnnounceSensorSweep()
        announce_msg.mechanism = self.mechanism_name

        # Announce all messages at once
        for task in self.tasks:
            announce_msg.tasks.append(self._construct_task_msg(task))

        return announce_msg

    def announce(self, e):
        rospy.loginfo("({0}) state: announce".format(self.mechanism_name))

        while not self.auctioneer.team_members:
            rospy.logdebug("..waiting for team to be non-empty")
            time.sleep(1)

        announcement_msg = self._construct_announcement_msg()
        stamp(announcement_msg)
        self.auctioneer.announce_pub.publish(announcement_msg)

        rospy.logdebug("Announcement:\n{0}".format(pp.pformat(announcement_msg)))

        self.fsm.announced()

    def collect_bids(self, e):
        rospy.loginfo("({0}) state: collect_bids".format(self.mechanism_name))

        bids = self.auctioneer.bids[self.auction_round]

        # For n tasks and m robots, the number of bids we expect to receive is:
        #  (2^n - 1) * m
        #  (|the powerset of tasks| minus the empty set) * m
        expected_count = (2 ** len(self.tasks) - 1) * len(self.auctioneer.team_members)

        bid_count = 0
        while bid_count < expected_count:
            self.auctioneer.bids_lock.acquire()

            try:
                bid_count = 0
                for robot_id in bids:
                    for task_tuple in bids[robot_id]:
                        bid_count += 1
            finally:
                self.auctioneer.bids_lock.release()

            rospy.loginfo('Received [{0}/{1}] bids...'.format(bid_count, expected_count))
            self.auctioneer.rate.sleep()

        self.fsm.bids_collected()

    def determine_winner(self, e):
        rospy.loginfo("({0}) state: determine_winner".format(self.mechanism_name))

        # 1. Create an OrderedSet set of task_ids
        tasks_oset = ordered_set.OrderedSet([t.task_id for t in self.tasks])

        # 2. Get a list of all possible partitions of the set
        t_partitions = partition.Partition(tasks_oset)

        # 3. For each partition, find the min-cost combination of bids
        min_cost = float(sys.maxint)   # A 'very large' value, to start with
        min_cost_partition = None     # A dict of (task set) => ([bid_value, robot_id])

        for t_partition in t_partitions:

            mincost_dict = defaultdict(list)

            robot_cost = defaultdict(float)

            # Each partition is a list of lists (of tasks)
            for t_list in t_partition:
                t_tuple = tuple(t_list)
                # rospy.loginfo("({0}) t_set: {1}".format(self.mechanism_name, pp.pformat(t_tuple)))

                min_bid, min_robot_id = self._min_bid_for_round(t_tuple, self.auction_round, robot_cost)

                mincost_dict[t_tuple] = [min_bid, min_robot_id]
                robot_cost[min_robot_id] += min_bid

            # partition_cost = sum(v[0] for v in mincost_dict.values())
            partition_cost = max(robot_cost.values())

            assn_str = ["{0} => {1} ".format(t, mincost_dict[t][1]) for t in mincost_dict]
            rospy.logdebug("partition cost: {0} for {1}".format(partition_cost, assn_str))

            if not min_cost_partition or partition_cost < min_cost:
                min_cost = partition_cost
                min_cost_partition = mincost_dict
                rospy.loginfo("min partition cost: {0}".format(partition_cost))
                rospy.loginfo("assignment: {0}".format(assn_str))

        # Done?
        self.fsm.winner_determined(min_cost_partition=min_cost_partition)

    def award(self, e):
        """ Construct and send an award message for each winner. """
        rospy.loginfo("({0}) state: award".format(self.mechanism_name))

        min_cost_partition = e.min_cost_partition

        for t_subset in min_cost_partition.keys():
            # t_subset is a *tuple* of task_ids
            [bid_value, robot_id] = min_cost_partition[t_subset]

            award_msg = mrta.msg.TaskAward()
            award_msg.robot_id = robot_id

            for task_id in t_subset:
                won_task = self._get_task_by_id(task_id)

                won_task.num_robots_allocated += 1
                if won_task.num_robots_allocated == won_task.num_robots:
                    won_task.awarded = True

                award_msg.tasks.append(self._construct_task_msg(won_task))

            self.auctioneer.award_pub.publish(award_msg)

            rospy.logdebug("sending award message:\n{0}".format(pp.pformat(award_msg)))
            time.sleep(1)


class AuctionMAN(Auction):
    """
    A manual "auction"
    """
    mechanism_name = 'MAN'

    def __init__(self, auctioneer=None, tasks=None, auction_round=None, task_winners=None):
        self.task_winners = task_winners
        rospy.loginfo('self.task_winners == {0}'.format(self.task_winners))
        super(AuctionMAN, self).__init__(auctioneer, tasks, auction_round)

    def _construct_announcement_msg(self):
        announce_msg = mrta.msg.AnnounceSensorSweep()
        announce_msg.mechanism = self.mechanism_name

        # Only announce one task (the first in the auctioneer's list)
        announce_msg.tasks.append(self._construct_task_msg(self.tasks[0]))

        return announce_msg

    def announce(self, e):
        rospy.loginfo("({0}) state: announce".format(self.mechanism_name))
        rospy.loginfo("..skipping!")

        self.fsm.announced()

    def collect_bids(self, e):
        rospy.loginfo("({0}) state: collect_bids".format(self.mechanism_name))
        rospy.loginfo("..skipping!")

        self.fsm.bids_collected()

    def determine_winner(self, e):
        rospy.loginfo("({0}) state: determine_winner".format(self.mechanism_name))
        rospy.loginfo("..skipping!")

        self.fsm.winner_determined()

    def award(self, e):
        """ Construct and send an award message for each task. """
        rospy.loginfo("({0}) state: award".format(self.mechanism_name))

        for task_id in self.task_winners:

            won_task = self._get_task_by_id(task_id)

            for winner_id in self.task_winners[task_id]:

                award_msg = mrta.msg.TaskAward()

                # award_msg.robot_id = team_cycle.next()
                award_msg.robot_id = winner_id

                task_msg = self._construct_task_msg(won_task)
                award_msg.tasks.append(task_msg)

                rospy.logdebug("sending award message:\n{0}".format(pp.pformat(award_msg)))

                stamp(award_msg)
                self.auctioneer.award_pub.publish(award_msg)

                # Remove/republish task marker with winning robot's color
                self.auctioneer.remove_task_marker(won_task.task_id)
                self.auctioneer.publish_task_marker(won_task, ROBOT_COLORS[winner_id])

                won_task.num_robots_allocated += 1

                self.auctioneer.awarded[task_id].extend(winner_id)

                # Mark the task as awarded if the task has been awarded to its required
                # number of robots
                if won_task.num_robots_allocated == won_task.num_robots:
                    won_task.awarded = True


class Auctioneer:

    def __init__(self, mechanism=None, task_file=None):
        """
        Initialize some ROS stuff (topics to publish/subscribe) and our state machine.
        """

        # Initialize our node
        # Do we need a special name for the auctioneer (i.e., not "auctioneer")?
        node_name = 'auctioneer'
        rospy.loginfo("Starting node '{0}'...".format(node_name))
        rospy.init_node(node_name)

        # Topics we wish to subscribe to
        self.bid_sub = self.status_sub = self.new_sub = None
        self.init_subscribers()

        # Topics we wish to publish
        self.experiment_pub = self.announce_pub = self.award_pub = self.debug_pub = self.marker_pub = None
        self.marker_id = 0
        self.init_publishers()

        # The rate at which we'll sleep while idle
        self.rate = rospy.Rate(RATE)

        # A lock (mutex) to prevent the data structure that stores bids
        # from being read and written to at the same time
        self.bids_lock = Lock()

        # A list of (node) names of robot team members.
        self.team_members = []

        # Keep track of team members' positions
        self.team_poses = defaultdict(geometry_msgs.msg.Pose)
        self.amcl_pose_subs = {}

        # A cycling iterator
        self._team_cycle = None

        # A list of (node) names team members who have completed
        # all of their tasks.
        self.team_members_completed = []

        # Keep track of which team members have send an 'AGENDA_CLEARED' message
        self.agenda_cleared = defaultdict(bool)

        # We will use one mechanism per run (for now)
        # self.mechanism = mechanism
        self.mechanism = rospy.get_param('~mechanism')

        # Tasks are loaded from a configuration file
        self.scenario_file = None
        try:
            self.scenario_file = rospy.get_param('~scenario_file')

            # # (Legacy cleanup) remove .yaml extension if it is present
            # self.scenario_id = self.scenario_id.replace('.yaml', '')
        except KeyError:
            rospy.logerr("Parameter 'scenario_file' has no value!")

        # Do we reallocate tasks or not?
        try:
            self.reallocate = rospy.get_param('~reallocate')
        except KeyError:
            rospy.logerr("Parameter 'reallocate' has no value!")

        rospy.loginfo("self.reallocate == {0}".format(self.reallocate))

        # Start up a planner proxy
        dummy_robot_name = rospy.get_param('~dummy_robot_name', "robot_0")
        # rospy.loginfo("Auctioneer: Starting PlannerProxy")
        # self.planner_proxy = mrta.mrta_planner_proxy.PlannerProxy(dummy_robot_name)

        # Scripted tasks that are not necessarily 'live' at the start of the experiment
        self.scripted_items = []
        self.scripted_items_by_id = {}

        # A simple list for now
        self.items = []

        # We also want to be able to get tasks by id
        self.items_by_id = {}

        # Timers for tasks to 'appear'
        self.item_timers = []

        # If a new task has been 'generated'. Hacky, refactor.
        self.new_item_added = False

        # To identify in which round bids are made for tasks
        self.auction_round = 0

        # Keep track of bids, indexed by auction_round, task_id and robot_id
        self.bids = defaultdict(int)

        # Keep track of which robots have been awarded which tasks
        # task_id => list of robot_name
        self.awarded = defaultdict(list)

        # Set up state machine.
        # See mrta/docs/auctioneer-fsm.png
        self.fsm = Fysom( 
            events=[
                ('startup', 'none', 'load_scenario'),
                ('scenario_loaded', 'load_scenario', 'identify_team'),
                ('do_identify_team', '*', 'identify_team'),
                ('team_identified', 'identify_team', 'idle'),
                ('have_items', 'idle', 'choose_mechanism'),
                ('allocation_complete', 'choose_mechanism', 'monitor_execution'),
                ('current_tasks_complete', 'monitor_execution', 'end_execution'),
                ('have_tasks', 'end_execution', 'idle'),
                ('all_scripted_items_complete', '*', 'end_experiment'),
            ],
            callbacks={
                # on-enter state handlers
                'onload_scenario': self.load_scenario,
                'onidentify_team': self.identify_team,
                'onidle': self.idle,
                'onchoose_mechanism': self.choose_mechanism,
                'onmonitor_execution': self.monitor_execution,
                'onend_execution': self.end_execution,
                'onend_experiment': self.end_experiment,
                # on-event handlers
            }
        )

        # Generate a unique, random experiment id
        self.experiment_id = str(uuid.uuid4())

        # Send a message to mark the beginning of the experiment
        # begin_exp_msg = mrta.msg.ExperimentEvent()
        # begin_exp_msg.experiment_id = self.experiment_id
        # begin_exp_msg.event = mrta.msg.ExperimentEvent.BEGIN_EXPERIMENT
        # stamp(begin_exp_msg)
        # self.experiment_pub.publish(begin_exp_msg)

        # Start the state machine
        self.fsm.startup()

    def init_subscribers(self):
        rospy.loginfo('Initializing subscribers...')

        # Listen for bids on '/tasks/bid'
        self.bid_sub = rospy.Subscriber('/tasks/bid',
                                        mrplan_msgs.msg.ItemBid,
                                        self.on_bid_received)

        # self.status_sub = rospy.Subscriber('/tasks/status',
        #                                    mrta.msg.TaskStatus,
        #                                    self.on_task_status)
        #
        # self.new_sub = rospy.Subscriber('/tasks/new',
        #                                 mrta.msg.SensorSweepTask,
        #                                 self.on_new_task)

        # Note: we also subscribe to team member positions in
        # identify_team(). We'd do it here, but can't until the
        # team has been identified.

        # For good measure...
        time.sleep(1)

    def init_publishers(self):
        rospy.loginfo('Initializing publishers...')

        # Announce experiment events on '/experiment'.
        # Importantly, 'BEGIN_ALLOCATION', 'END_ALLOCATION', and
        # 'BEGIN_EXECUTION'.
        # self.experiment_pub = rospy.Publisher('/experiment',
        #                                       mrta.msg.ExperimentEvent,
        #                                       queue_size=3)

        # Announce tasks on '/tasks/announce'. For the moment we will only
        # announce sensor sweep tasks.
        self.announce_pub = rospy.Publisher('/tasks/announce',
                                            mrplan_msgs.msg.Item,
                                            latch=True,
                                            queue_size=3)

        # Award tasks on '/tasks/award'
        self.award_pub = rospy.Publisher('/tasks/award',
                                         mrplan_msgs.msg.ItemAward,
                                         latch=True,
                                         queue_size=10)

        # # '/debug'
        # self.debug_pub = rospy.Publisher('/debug',
        #                                  mrta.msg.Debug,
        #                                  queue_size=3)

        # Markers for tasks
        self.marker_pub = rospy.Publisher('visualization_marker',
                                          visualization_msgs.msg.Marker,
                                          queue_size=3)

        # For good measure...
        time.sleep(1)

    def on_new_task(self, new_task_msg):
        rospy.loginfo("Received new task: {0}".format(pp.pformat(new_task_msg)))
        
        new_task = mrta.SensorSweepTask(str(new_task_msg.task.task_id),
                                        float(new_task_msg.location.x),
                                        float(new_task_msg.location.y))
        self.items.append(new_task)
        self.items_by_id[new_task_msg.task.task_id] = new_task

    def publish_task_marker(self, task, color=[0.5, 0.5, 0.5]):
        marker_msg = visualization_msgs.msg.Marker()

        marker_msg.header.frame_id = '/map'
        marker_msg.header.stamp = rospy.Time()
        marker_msg.ns = 'mrta'
        marker_msg.id = int(task.task_id)

        if task.num_robots > 1:
            marker_msg.type = visualization_msgs.msg.Marker.CUBE
        else:
            marker_msg.type = visualization_msgs.msg.Marker.SPHERE

        marker_msg.action = visualization_msgs.msg.Marker.ADD

        marker_msg.pose.position.x = task.location.x
        marker_msg.pose.position.y = task.location.y
        marker_msg.pose.position.z = 0
        marker_msg.pose.orientation.x = 0.0
        marker_msg.pose.orientation.y = 0.0
        marker_msg.pose.orientation.z = 0.0
        marker_msg.pose.orientation.w = 1.0

        marker_msg.scale.x = 0.2
        marker_msg.scale.y = 0.2
        marker_msg.scale.z = 0.2

        marker_msg.color.a = 1.0
        marker_msg.color.r = color[0]
        marker_msg.color.g = color[1]
        marker_msg.color.b = color[2]

        marker_msg.text = task.task_id

        self.marker_pub.publish(marker_msg)

        self.marker_id += 1

        marker_text_msg = visualization_msgs.msg.Marker()

        marker_text_msg.header.frame_id = '/map'
        marker_text_msg.header.stamp = rospy.Time()
        marker_text_msg.ns = 'mrta'
        marker_text_msg.id = int(task.task_id) + 100
        marker_text_msg.type = visualization_msgs.msg.Marker.TEXT_VIEW_FACING
        marker_text_msg.action = visualization_msgs.msg.Marker.ADD

        marker_text_msg.pose.position.x = task.location.x
        marker_text_msg.pose.position.y = task.location.y - 0.25
        marker_text_msg.pose.position.z = 0
        marker_text_msg.pose.orientation.x = 0.0
        marker_text_msg.pose.orientation.y = 0.0
        marker_text_msg.pose.orientation.z = 0.0
        marker_text_msg.pose.orientation.w = 1.0

        marker_text_msg.scale.x = 0.2
        marker_text_msg.scale.y = 0.2
        marker_text_msg.scale.z = 0.2

        marker_text_msg.color.a = 1.0
        marker_text_msg.color.r = 1.0
        marker_text_msg.color.g = 1.0
        marker_text_msg.color.b = 1.0

        marker_text_msg.text = "T{0}".format(task.task_id)

        self.marker_pub.publish(marker_text_msg)

        self.marker_id += 1

    def remove_task_marker(self, task_id):
        marker_msg = visualization_msgs.msg.Marker()
        marker_msg.header.frame_id = '/map'
        marker_msg.header.stamp = rospy.Time()
        marker_msg.ns = 'mrta'
        marker_msg.id = int(task_id)
        marker_msg.action = visualization_msgs.msg.Marker.DELETE

        self.marker_pub.publish(marker_msg)

        marker_text_msg = visualization_msgs.msg.Marker()
        marker_text_msg.header.frame_id = '/map'
        marker_text_msg.header.stamp = rospy.Time()
        marker_text_msg.ns = 'mrta'
        marker_text_msg.id = int(task_id) + 100
        marker_text_msg.action = visualization_msgs.msg.Marker.DELETE

        self.marker_pub.publish(marker_text_msg)

    def add_scripted_item(self, item_id):
        rospy.loginfo("'Adding' scripted task {0}...".format(item_id))

        scripted_item = self.scripted_items_by_id[item_id]
        rospy.loginfo("Adding item: {0}".format(pp.pformat(scripted_item)))
        self.items.append(scripted_item)
        self.items_by_id[scripted_item.item_id] = scripted_item

        self.new_item_added = True
        rospy.loginfo("self.new_item_added=={0}".format(self.new_item_added))

        # rospy.loginfo("Publishing marker for {0}".format(scripted_item.task_id))
        # self.publish_task_marker(scripted_item)

        rospy.loginfo("add_scripted_item(): current state=={0}".format(self.fsm.current))

    def load_scenario(self, data):
        self.load_scenario_from_file()
        # self.load_scenario_from_db()

        rospy.loginfo("Scripted Items:\n{0}".format(pp.pformat(self.scripted_items_by_id)))

        # Start timers
        for item_timer in self.item_timers:
            item_timer.start()
            # Sleep a tiny bit to make sure they're loaded
            time.sleep(0.1)

        self.fsm.scenario_loaded()

    def load_scenario_from_db(self):
        pass

    def load_scenario_from_file(self):
        rospy.loginfo("Loading tasks from {0}...".format(self.scenario_file))

        if not self.scenario_file:
            rospy.logerror("No scenario file given!")
            return

        try:
            # pkg = rospkg.RosPack()
            # pkg_path = pkg.get_path('mrplan_auctioneer')
            #
            # scenario_file = open(os.path.join(pkg_path, 'scenarios', self.scenario_file), 'rb')

            scenario_file = open(self.scenario_file, 'rb')

            yaml_items = yaml.load(scenario_file)

            for yaml_item in yaml_items:
                new_item = Item(str(yaml_item['item_id']),
                                [int(yaml_item['grey_count']),
                                 int(yaml_item['red_count']),
                                 int(yaml_item['blue_count']),
                                 int(yaml_item['green_count']),
                                 int(yaml_item['white_count']),
                                 int(yaml_item['black_count'])],
                                str(yaml_item['site']))

                self.scripted_items.append(new_item)
                self.scripted_items_by_id[str(yaml_item['item_id'])] = new_item
                
                self.item_timers.append(Timer(float(yaml_item['arrival_time']),
                                              self.add_scripted_item,
                                              [str(yaml_item['item_id'])]))

                rospy.loginfo("Added item {0} and started its timer".format(new_item.item_id))

        except Exception as e:
            rospy.logerr("Can't open/parse scenario file {0}!".format(self.scenario_file))
            e_type, e_value, e_traceback = sys.exc_info()
            rospy.logerr("{0}: {1}".format(e_type, e_value))
            # rospy.logerr("{0}".format(e_traceback.format_exc()))

    def on_teammate_pose_received(self, amcl_pose_msg, r_name):
        rospy.logdebug("(Auctioneer) on_teammate_pose_received ({0})".format(r_name))

        # amcl_pose_msg is typed as geometry_msgs/PoseWithCovarianceStamped.
        # We'll just keep track of amcl_pose_msg.pose.pose, which is typed as
        # geometry_msgs/Pose
        other_pose = amcl_pose_msg.pose.pose
        self.team_poses[r_name] = other_pose
        rospy.logdebug("(Auctioneer) {0} is now at {1}".format(r_name, pp.pformat(other_pose)))

    def identify_team(self, data):
        rospy.loginfo("Identifying team...")

        # In the 'rosnode' utility/module, _sub_rosnode_listnodes() returns a
        # newline-separated list of the names of all nodes in the graph.
        # See http://wiki.ros.org/rosnode
        node_list = rosnode._sub_rosnode_listnodes().split()

        # We're finding namespaces that look like the following pattern
        # (in parens):
        name_pat = re.compile('/(.*)/mrta_robot_controller')
        for node_name in node_list:
            m = name_pat.match(node_name)
            if m:
                teammate_name = m.group(1)
                rospy.loginfo("Adding {0} to team".format(teammate_name))
                self.team_members.append(teammate_name)

        # TEMP HACK!
        # self.team_members = ['robot_1', 'robot_2', 'robot_3']
        self.team_members = ['robot_1']

        self._team_cycle = itertools.cycle(self.team_members)
        
        # Subscribe to and keep track of team members' positions
        # '/robot_<n>/amcl_pose'
        for team_member in self.team_members:

            self.amcl_pose_subs[team_member] = rospy.Subscriber(
                "/{0}/amcl_pose".format(team_member),
                geometry_msgs.msg.PoseWithCovarianceStamped,
                self.on_teammate_pose_received, callback_args=team_member)
            rospy.loginfo("subscribed to /{0}/amcl_pose".format(team_member))

        rospy.loginfo("Team members: {0}".format(self.team_members))

        self.fsm.team_identified()

    def team_agenda_cleared(self):
        """
        Only return True if all team members have sent an 'AGENDA_CLEARED' message
        :return:
        """
        for team_member in self.team_members:
            if not self.agenda_cleared[team_member]:
                return False
        return True

    def idle(self, data):
        rospy.loginfo("state: idle")

        # If our item pool (self.items) is empty, let's assume we were
        # started up with no predefined mission (i.e., no task_file startup
        # parameter). Idle here until some task appears, presumably via a
        # messages on the /tasks/new topic.
        while not self.items:
            self.rate.sleep()

        rospy.loginfo("self.items=={0}".format(pp.pformat(self.items)))

        # There are scripted (dynamic) tasks yet to come. Idle until they arrive.
        incomplete_scripted_items = True
        while incomplete_scripted_items:

            # self.rate.sleep()
            time.sleep(0.1)

            incomplete_scripted_items = False

            for scripted_item in self.scripted_items:
                if not scripted_item.completed:
                    incomplete_scripted_items = True
                    break

            unallocated = False
            for item in self.items:
                if not item.awarded:
                    unallocated = True
                    break

            if unallocated:
                break

        if unallocated:
            # Transition to the "choose_mechanism" state
            self.fsm.have_items()
        else:
            rospy.loginfo("All scripted items complete...")
            self.fsm.all_scripted_items_complete()

    def p_medians_greedy(self, matrix, p):
        pass

    def find_p_medians(self, matrix, p):
        """
        Find p medians, given a distance-weighted adjacency matrix
        :param matrix: a distance-weighted adjacency matrix
        :param p: the number of medians to find
        :return: a set of ids of median
        """
        p_medians = []

        # Greedy
        return self.p_medians_greedy(matrix, p)

        # Teitz-Bart
        return p_medians

    def build_robot_graph(self):
        robot_graph = igraph.Graph()
        robot_graph.add_vertices(self.team_members)

        # Turn on weighting
        robot_graph.es['weight'] = 1.0

        # For every pair of robots
        for pair in combinations(self.team_members, 2):
            first_robot_name = pair[0]
            second_robot_name = pair[1]

            source_point = mrta.Point(self.team_poses[first_robot_name].position.x,
                                      self.team_poses[first_robot_name].position.y)
            source_pose = self.planner_proxy._point_to_pose(source_point)

            target_point = mrta.Point(self.team_poses[second_robot_name].position.x,
                                      self.team_poses[second_robot_name].position.y)
            target_pose = self.planner_proxy._point_to_pose(target_point)

            distance = self.planner_proxy.get_path_cost(source_pose, target_pose)

            robot_graph[first_robot_name, second_robot_name] = distance

        dist_matrix = robot_graph.get_adjacency(type=2, attribute='weight').data

        print("robot_graph: {0}, distances: {1}".format(robot_graph.summary(),
                                                        robot_graph.es['weight']))
        # print("Distance-weighted adjacency matrix: {0}".format(pp.pformat(dist_matrix)))

        # robot_graph_mst = robot_graph.spanning_tree(weights=robot_graph.es['weight'])
        # print("robot_graph_mst: {0}, distances: {1}".format(robot_graph_mst.summary(),
        #                                                     robot_graph_mst.es['weight']))
        # print task_graph_mst
        team_diameter = robot_graph.diameter(directed=False, weights='weight')
        return robot_graph

    def get_greedy_median_count(self, median_tasks):

        # Keep track of every robot's distance to every median
        # Key is robot id, value is a dict of median task_id => distance
        distance_to_all_medians = {}
        for robot_name in self.team_members:
            distance_to_all_medians[robot_name] = {}

        # For each robot, count how many medians it is the "closest" to
        greedy_median_count = {}
        for robot_name in self.team_members:
            greedy_median_count[robot_name] = 0

        for median_task in median_tasks:
            min_robot_id = None
            min_robot_distance = None

            source_point = mrta.Point(median_task.location.x,
                                      median_task.location.y)
            source_pose = self.planner_proxy._point_to_pose(source_point)

            for robot_name in self.team_members:
                target_point = mrta.Point(self.team_poses[robot_name].position.x,
                                          self.team_poses[robot_name].position.y)
                target_pose = self.planner_proxy._point_to_pose(target_point)

                distance = self.planner_proxy.get_path_cost(source_pose, target_pose)

                distance_to_all_medians[robot_name][median_task.task_id] = distance

                if not min_robot_distance or distance < min_robot_distance:
                    min_robot_id = robot_name
                    min_robot_distance = distance

            greedy_median_count[min_robot_id] += 1

        return greedy_median_count, distance_to_all_medians

    def select_mechanism_dynamic(self, unallocated, configured_mechanism):
        """ Decide which mechanism to use given a list of unallocated tasks.

        Our first go at this will use ideas from facility-location to choose
        between SSI and PSI.

        :param unallocated: a list of as-yet unallocated tasks
        :return: "OSI", "PSI", "SSI", "RR", "SUM", "MAX"
        """
        rospy.loginfo("Auctioneer: Choosing mechanism dynamically")
        dynamic_mechanism = "PSI"

        # Return early with the default mechanism if the set of tasks is less
        # than a certain amount
        if len(unallocated) <= 2:
            return dynamic_mechanism

        # Return early if no classifier or features have been set
        if not self.classifier or not self.feature_names:
            return dynamic_mechanism

        # 1. Build a complete graph of unallocated tasks.
        #    Use the global planner to find a path between each pair of tasks

        # Create a graph. Vertices will be tasks.
        task_graph = igraph.Graph()
        task_graph.add_vertices([t.task_id for t in unallocated])

        # Turn on weighting
        task_graph.es['weight'] = 1.0

        # Add an edge between every pair of vertices
        for pair in combinations([t.task_id for t in unallocated], 2):
            # The task ids of the source and target
            source_id = pair[0]
            target_id = pair[1]

            # The actual Task objects of the source and target
            source = self.items_by_id[source_id]
            target = self.items_by_id[target_id]

            # A mrta.Point instance
            source_point = source.location
            # A geometry_msgs.msg.Pose instance
            source_pose = self.planner_proxy._point_to_pose(source_point)

            # A mrta.Point instance
            target_point = target.location
            # A geometry_msgs.msg.Pose instance
            target_pose = self.planner_proxy._point_to_pose(target_point)

            distance = self.planner_proxy.get_path_cost(source_pose, target_pose)

            rospy.loginfo("Auctioneer: distance from task {0} ({1},{2}) to task {3} ({4},{5}) is {6}".format(source_id,
                                                                                                             source_point.x,
                                                                                                             source_point.y,
                                                                                                             target_id,
                                                                                                             target_point.x,
                                                                                                             target_point.y,
                                                                                                             distance))
            print task_graph

            # Add the edge from source to target to task_graph
            # task_graph.add_edge(source_id, target_id)
            task_graph[source_id, target_id] = distance

        rospy.loginfo("Auctioneer: task_graph: {0}, distances: {1}".format(task_graph.summary(),
                                                                           task_graph.es['weight']))

        # Get a distance-weighted adjacency matrix
        dist_matrix = task_graph.get_adjacency(type=2, attribute='weight').data
        rospy.loginfo("Distance-weighted adjacency matrix: {0}".format(pp.pformat(dist_matrix)))

        # 2. We need to get rid of cycles in the graph. Turn it into a
        # (minimum-spanning) tree
        task_graph_mst = task_graph.spanning_tree(weights=task_graph.es['weight'])
        rospy.loginfo("Auctioneer: task_graph_mst: {0}, distances: {1}".format(task_graph_mst.summary(),
                                                                               task_graph_mst.es['weight']))
        # print task_graph_mst

        # 3. Find ideal facility locations (p-medians) in the tree.

        # Let's start with a simple (but maybe not optimal) greedy algorithm
        p = 3
        median_vertex_ids = pmed_greedy(dist_matrix, p)

        median_task_ids = [task_graph.vs[v_id]['name'] for v_id in median_vertex_ids]
        median_tasks = [self.items_by_id[t_id] for t_id in median_task_ids]

        debug_msg = mrta.msg.Debug()
        debug_msg.key = 'auctioneer-median-ids'
        debug_msg.value = "median task ids: [{0}]".format(','.join(median_task_ids))
        self.debug_pub.publish(debug_msg)

        # 4. If The team (average, max?) distance to the facility locations
        # is greater than ?, choose SSI. Otherwise, choose PSI.

        team_distance_to_assigned_medians = defaultdict(float)

        # Assign each team member to the median closest to it. We'll assign medians to
        # team members in a 1-1 correspondence, so we'll need candidate lists

        median_task_candidates = median_tasks[:]
        team_member_candidates = self.team_members[:]

        while median_task_candidates and team_member_candidates:

            min_distance_to_median = None
            min_median_task = None
            min_team_member = None

            for team_member_candidate in team_member_candidates:
                # A geometry_msgs.msg.Pose instance
                member_pose = self.team_poses[team_member_candidate]

                for median_task_candidate in median_task_candidates:
                    median_candidate_point = median_task_candidate.location
                    # A geometry_msgs.msg.Pose instance
                    median_candidate_pose = self.planner_proxy._point_to_pose(median_candidate_point)

                    distance = self.planner_proxy.get_path_cost(member_pose, median_candidate_pose)

                    if not min_distance_to_median or distance < min_distance_to_median:
                        min_distance_to_median = distance
                        min_median_task = median_task_candidate
                        min_team_member = team_member_candidate

            rospy.loginfo("Auctioneer: {0}'s distance to its nearest median (task {1}) == {2}".format(min_team_member,
                                                                                                      min_median_task.task_id,
                                                                                                      min_distance_to_median))

            debug_msg = mrta.msg.Debug()
            debug_msg.key = 'auctioneer-median-distance'
            debug_msg.value = "robot [{0}] distance to its nearest median task [{1}] == [{2}]".format(min_team_member,
                                                                                                      min_median_task.task_id,
                                                                                                      min_distance_to_median)
            self.debug_pub.publish(debug_msg)

            team_distance_to_assigned_medians[min_team_member] = min_distance_to_median

            median_task_candidates.remove(min_median_task)
            team_member_candidates.remove(min_team_member)

        total_dist_to_assigned_medians = 0.0
        avg_dist_to_assigned_medians = 0.0

        for team_member in team_distance_to_assigned_medians:
            total_dist_to_assigned_medians += team_distance_to_assigned_medians[team_member]

        avg_dist_to_assigned_medians = total_dist_to_assigned_medians / len(team_distance_to_assigned_medians) * 1.0

        rospy.loginfo("Total distance to medians: {0}, Average distance to medians: {1}".format(total_dist_to_assigned_medians,
                                                                                                avg_dist_to_assigned_medians))

        greedy_median_count, team_distance_to_all_medians = self.get_greedy_median_count(median_tasks)
        greedy_median_count_spread = max(greedy_median_count.values()) - min(greedy_median_count.values())

        min_distance_to_assigned_median = min(team_distance_to_assigned_medians.values())
        max_distance_to_assigned_median = max(team_distance_to_assigned_medians.values())
        total_distance_to_assigned_medians = sum(team_distance_to_assigned_medians.values())

        assigned_median_distance_spread = max_distance_to_assigned_median - min_distance_to_assigned_median

        total_distance_to_all_medians = 0.0
        max_distance_to_any_median = None
        min_distance_to_any_median = None
        for robot_name in team_distance_to_all_medians:
            for median_task_id in team_distance_to_all_medians[robot_name]:

                robot_median_distance = team_distance_to_all_medians[robot_name][median_task_id]

                if not max_distance_to_any_median or robot_median_distance > max_distance_to_any_median:
                    max_distance_to_any_median = robot_median_distance

                if not min_distance_to_any_median or robot_median_distance < min_distance_to_any_median:
                    min_distance_to_any_median = robot_median_distance

                total_distance_to_all_medians += robot_median_distance

        total_median_distance_spread = max_distance_to_any_median - min_distance_to_any_median

        robot_graph = self.build_robot_graph()

        team_diameter = robot_graph.diameter(directed=False, weights='weight')
        print "team diameter: {0}".format(team_diameter)

        average_teammate_distance = np.mean(robot_graph.es['weight'])
        print "average teammate distance: {0}".format(average_teammate_distance)

        # Find the euclidean center of the team, then measure the average team
        # member distance to that center.
        team_centroid_x = sum([self.team_poses[rn].position.x for rn in self.team_members]) * 1. / len(self.team_members)
        team_centroid_y = sum([self.team_poses[rn].position.y for rn in self.team_members]) * 1. / len(self.team_members)

        total_team_centroid_distance = 0.0
        for robot_name in self.team_members:
            robot_x = self.team_poses[robot_name].position.x
            robot_y = self.team_poses[robot_name].position.y
            total_team_centroid_distance += scipy.spatial.distance.euclidean((robot_x, robot_y), (team_centroid_x, team_centroid_y))

        average_team_centroid_distance = total_team_centroid_distance * 1. / len(self.team_members)
        print "average team centroid distance: {0}".format(average_team_centroid_distance)

        # features = [greedy_median_count_spread,
        #             min_distance_to_assigned_median,
        #             total_distance_to_assigned_medians,
        #             team_diameter]

        psi_spread = 0

        if configured_mechanism == 'SEL':
            # Run PPSI
            auction_ppsi = AuctionPPSI(self, unallocated, self.auction_round)

            # Get PPSI allocation and compute PSI spread: task_max - task_min, where
            #
            #   task_max = greatest number of tasks awarded to a single robot
            #   task_min = least number of tasks awarded to a single robot

            if self.ppsi_task_winners:
                robot_award_counts = defaultdict(int)

                for task_id in self.ppsi_task_winners:
                    winner_ids = self.ppsi_task_winners[task_id]

                    for winner_id in winner_ids:
                        robot_award_counts[winner_id] += 1

                psi_spread = max(robot_award_counts.values()) - min(robot_award_counts.values())

        rospy.loginfo('PSI_SPREAD == {0}'.format(psi_spread))

        features_map = {'MAX_DISTANCE_TO_ASSIGNED_MEDIAN': max_distance_to_assigned_median,
                        'MIN_DISTANCE_TO_ASSIGNED_MEDIAN': min_distance_to_assigned_median,
                        'MAX_DISTANCE_TO_ANY_MEDIAN': max_distance_to_any_median,
                        'MIN_DISTANCE_TO_ANY_MEDIAN': min_distance_to_any_median,
                        'ASSIGNED_MEDIAN_DISTANCE_SPREAD': assigned_median_distance_spread,
                        'TOTAL_MEDIAN_DISTANCE_SPREAD': total_median_distance_spread,
                        'GREEDY_MEDIAN_COUNT_SPREAD': greedy_median_count_spread,
                        'TOTAL_DISTANCE_TO_ASSIGNED_MEDIANS': total_dist_to_assigned_medians,
                        'TEAM_DIAMETER': team_diameter,
                        'AVERAGE_TEAMMATE_DISTANCE': average_teammate_distance,
                        'AVERAGE_TEAM_CENTROID_DISTANCE': average_team_centroid_distance,
                        'PSI_SPREAD': psi_spread}

        features = np.reshape([features_map[f] for f in self.feature_names], (1, -1))

        rospy.loginfo("Auctioneer: features: {0}".format(pp.pformat(features)))

        dynamic_mechanism = self.classifier.predict(features)[0]

        rospy.loginfo("Auctioneer: select_mechanism_dynamic() chose {0}".format(dynamic_mechanism))

        debug_msg = mrta.msg.Debug()
        debug_msg.key = 'auctioneer-selected-mechanism'
        debug_msg.value = dynamic_mechanism
        self.debug_pub.publish(debug_msg)

        return dynamic_mechanism

    def choose_mechanism(self, e):
        rospy.loginfo("state: choose_mechanism")

        time.sleep(0.2)

        # # Send a message to mark the beginning of the allocation phase of
        # # the experiment
        # begin_alloc_msg = mrta.msg.ExperimentEvent()
        # begin_alloc_msg.experiment_id = self.experiment_id
        # begin_alloc_msg.event = mrta.msg.ExperimentEvent.BEGIN_ALLOCATION
        # stamp(begin_alloc_msg)
        # self.experiment_pub.publish(begin_alloc_msg)

        rospy.loginfo("state: choose_mechanism 2")

        # If we are doing task REallocation, pause here until we receive an
        # AGENDA_CLEARED TaskStatus message from each member of the team before
        # moving on to allocation.
        if self.reallocate:
            rospy.loginfo("self.reallocation==True")

            while not self.team_agenda_cleared():
                # self.rate.sleep()
                time.sleep(0.1)

            # It's now safe to continue, but first reset 'AGENDA_CLEARED' flag for
            # all team members
            for team_member in self.team_members:
                self.agenda_cleared[team_member] = False

        rospy.loginfo("state: choose_mechanism 3")

        # For now, use the single mechanism given to us as a parameter
        rospy.loginfo("  {0}".format(self.mechanism))

        # If we are REallocating, for each incomplete item i, set i.awarded = False
        if self.reallocate:
            for i in self.items:
                if not i.completed:
                    i.awarded = False

        # As long as there are unallocated tasks, choose a mechanism and
        # allocate them. An unallocated task should be both incomplete and unawarded.
        while True:
            unallocated = []
            for item in self.items:
                if not item.awarded:
                    unallocated.append(item)

            if not unallocated:
                break

            self.auction_round += 1
            self.bids[self.auction_round] = defaultdict(str)

            # # Send a message to mark the beginning of the mechanism-choosing phase of
            # # the experiment
            # begin_choose_msg = mrta.msg.ExperimentEvent()
            # begin_choose_msg.experiment_id = self.experiment_id
            # begin_choose_msg.event = mrta.msg.ExperimentEvent.BEGIN_SELECT_MECHANISM
            # stamp(begin_choose_msg)
            # self.experiment_pub.publish(begin_choose_msg)

            # Use one particular mechanism by default, defined in a startup parameter
            mechanism = self.mechanism

            rospy.loginfo("######################################################")
            rospy.loginfo("######## choose_mechanism(): mechanism == {0} ########".format(mechanism))
            rospy.loginfo("######################################################")

            # If we're choosing a mechanism a runtime
#            if self.dynamic_mechanism:
            if mechanism == 'SEL':
                mechanism = self.select_mechanism_dynamic(unallocated, mechanism)
                rospy.loginfo("Auctioneer: Mechanism {0} selected dynamically".format(mechanism))

                # At this point, PSI has actually already been partially run via PPSI. If PSI
                # was selected, we want to finish it (actually award its allocation) via 'MAN',
                # the manual allocation mechanism. The allocation will have been stored in
                # self.ppsi_task_winners
                if mechanism == 'PSI':
                    mechanism = 'MAN'
                    rospy.loginfo("Auctioneer: Running 'MAN' to finish the allocation.")

            else:
                # Call it anyway to record information about medians and distance. Ignore the result
                # (i.e., don't assign its return value to the variable 'mechanism')
                self.select_mechanism_dynamic(unallocated, mechanism)
                rospy.loginfo("Auctioneer: Mechanism {0} selected dynamically".format(mechanism))

            # # Send a message to mark the end of the mechanism-choosing phase of
            # # the experiment
            # end_choose_msg = mrta.msg.ExperimentEvent()
            # end_choose_msg.experiment_id = self.experiment_id
            # end_choose_msg.event = mrta.msg.ExperimentEvent.END_SELECT_MECHANISM
            # stamp(end_choose_msg)
            # self.experiment_pub.publish(end_choose_msg)

            if mechanism == 'OSI':
                auction_osi = AuctionOSI(self, unallocated, self.auction_round)
            elif mechanism == 'PSI':
                auction_psi = AuctionPSI(self, unallocated, self.auction_round)
            elif mechanism == 'SSI':
                auction_ssi = AuctionSSI(self, unallocated, self.auction_round)
            elif mechanism == 'RR':
                auction_rr = AuctionRR(self, unallocated, self.auction_round)
            elif mechanism == 'SUM':
                auction_sum = AuctionSUM(self, unallocated, self.auction_round)
            elif mechanism == 'MAX':
                auction_max = AuctionMAX(self, unallocated, self.auction_round)
            elif mechanism == 'MAN':
                auction_man = AuctionMAN(self, unallocated, self.auction_round, self.ppsi_task_winners)

            # If this is uncommented, mechanism selection happens only once.
            # This has important implications! Consider if this is really what you want to do!
            rospy.logdebug("######## choose_mechanism(): setting self.mechanism to {0} ########".format(mechanism))
            self.mechanism = mechanism

        # An auction runs when it is instantiated (above).
        # At this point, we can (safely?) consider all previously unallocated
        # tasks to have been allocated
        self.new_item_added = False
        rospy.loginfo("self.new_item_added == {0}".format(self.new_item_added))

        # # We are finished allocating tasks. Signal the end of the allocation
        # # phase and the beginning of the execution phase.
        # end_alloc_msg = mrta.msg.ExperimentEvent()
        # end_alloc_msg.experiment_id = self.experiment_id
        # end_alloc_msg.event = mrta.msg.ExperimentEvent.END_ALLOCATION
        # stamp(end_alloc_msg)
        # self.experiment_pub.publish(end_alloc_msg)

        begin_exec_msg = mrta.msg.ExperimentEvent()
        begin_exec_msg.experiment_id = self.experiment_id
        begin_exec_msg.event = mrta.msg.ExperimentEvent.BEGIN_EXECUTION
        stamp(begin_exec_msg)
        self.experiment_pub.publish(begin_exec_msg)

        self.fsm.allocation_complete()

    def on_bid_received(self, bid_msg):
        task_ids = bid_msg.task_ids
        robot_id = bid_msg.robot_id
        bid = bid_msg.bid

        self.bids_lock.acquire()

        round_bids = self.bids[self.auction_round]
        
        if not round_bids[robot_id]:
            round_bids[robot_id] = {}

        # task_ids here is a *tuple* because a list can't be used as a dict key
        rospy.loginfo("Adding bid from {0} for {1} with value {2}".format(robot_id, tuple(task_ids), float(bid)))

        round_bids[robot_id][tuple(task_ids)] = float(bid)

        self.bids_lock.release()

        rospy.logdebug("{0} bid {1} for task {2} in auction round {3}".format(
            robot_id, bid, task_ids, self.auction_round))

    def on_task_status(self, status_msg):
        robot_id = status_msg.robot_id
        task_id = status_msg.task_id
        status = status_msg.status

        # We mainly want to keep track of robots that have
        # completed all of their tasks
        if status == mrta.msg.TaskStatus.ALL_TASKS_COMPLETE:
            rospy.loginfo("Received ALL_TASKS_COMPLETE from {0}".format(robot_id))
            self.team_members_completed.append(robot_id)

        elif status == mrta.msg.TaskStatus.SUCCESS:
            rospy.loginfo("{0} has completed task {1}".format(robot_id, task_id))

            completed_task = self.items_by_id[task_id]
            completed_task.completed = True

            # Remove/republish task marker to indicate completion (colored white?).
            self.remove_task_marker(completed_task.task_id)
            self.publish_task_marker(completed_task, (1.0, 1.0, 1.0))

        elif status == mrta.msg.TaskStatus.AGENDA_CLEARED:
            robot_id = status_msg.robot_id
            self.agenda_cleared[robot_id] = True
            rospy.loginfo("{0} has sent an 'AGENDA_CLEARED' message".format(robot_id))

    def monitor_execution(self, e):
        rospy.loginfo('state: monitor_execution')

        # Wait until all of the tasks (that have been allocated so far) are complete
        incomplete = True
        while incomplete and not self.new_item_added:

            incomplete = False
            for item in self.items:
                if not item.completed:
                    incomplete = True
                    break

            # time.sleep(0.2)
            self.rate.sleep()

        rospy.loginfo("Stopping task execution.")
        rospy.loginfo("incomplete=={0}".format(incomplete))
        rospy.loginfo("self.new_task_added=={0}".format(self.new_item_added))

        # Either:
        # 1. All tasks (that have been allocated so far) have been completed.
        # OR
        # 2. Some new, scripted task has been added
        # End the current execution phase of the experiment.
        self.fsm.current_tasks_complete()

    def end_execution(self, e):
        rospy.loginfo("state: end_execution")

        # Send a message to mark the end of the execution phase
        end_exec_msg = mrta.msg.ExperimentEvent()
        end_exec_msg.experiment_id = self.experiment_id
        end_exec_msg.event = mrta.msg.ExperimentEvent.END_EXECUTION
        stamp(end_exec_msg)
        self.experiment_pub.publish(end_exec_msg)

        incomplete_scripted_tasks = False
        for scripted_task in self.scripted_items:
            if not scripted_task.completed:
                incomplete_scripted_tasks = True
                break
        
        if incomplete_scripted_tasks:
            rospy.loginfo("end_execution: there are incomplete scripted tasks")
            self.fsm.have_items()
        else:
            rospy.loginfo("end_execution: all scripted tasks are complete")
            self.fsm.all_scripted_items_complete()

    def end_experiment(self, e):
        rospy.loginfo("state: end_experiment")

        # Send a message to mark the end of the experiment
        end_exp_msg = mrta.msg.ExperimentEvent()
        end_exp_msg.experiment_id = self.experiment_id
        end_exp_msg.event = mrta.msg.ExperimentEvent.END_EXPERIMENT
        stamp(end_exp_msg)
        self.experiment_pub.publish(end_exp_msg)

        rospy.loginfo("Shutting down...")

        # Instead of exiting, wait to be shut down from outside
        while not rospy.is_shutdown():
            self.rate.sleep()


if __name__ == '__main__':
    # Exit on ctrl-C
    signal.signal(signal.SIGINT, on_sigint)

    try:
        argv = rospy.myargv(argv=sys.argv[1:])
        auc = Auctioneer(*argv)
    except rospy.ROSInterruptException:
        pass
