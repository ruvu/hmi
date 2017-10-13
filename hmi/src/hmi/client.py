#!/usr/bin/env python
import random
from collections import namedtuple

import rospy
from actionlib import SimpleActionClient, GoalStatus
from hmi.common import random_sentences, result_from_ros, verify_grammar
from hmi_msgs.msg import QueryAction, QueryGoal


class TimeoutException(Exception):
    pass


def _truncate(data):
    return (data[:75] + '..') if len(data) > 75 else data


def _print_example(sentence):
    rospy.loginfo("Example: \x1b[1;44m'{}'\x1b[0m".format(sentence))


def _print_result(result):
    rospy.loginfo("Robot heard \x1b[1;42m'{}'\x1b[0m {}".format(result.sentence, result.semantics))


def _print_timeout():
    rospy.loginfo("Robot did not hear you \x1b[1;43m(timeout)\x1b[0m")


def _print_generic_failure():
    rospy.logerr("Robot did not hear you \x1b[1;37;41m(speech failed)\x1b[0m")


class Client(object):
    def __init__(self, name=None, simple_action_client=None):
        """
        Wrap the actionlib interface with the API
        """

        if not (bool(name) ^ bool(simple_action_client)):
            raise ValueError('name or simple_action_client should be set, but not both')

        if simple_action_client:
            self._client = simple_action_client
        else:
            self._client = SimpleActionClient(name, QueryAction)
            rospy.loginfo('waiting for "%s" server', name)
            self._client.wait_for_server()

        self._feedback = False
        self.last_talker_id = ""

    def _feedback_callback(self, feedback):
        rospy.loginfo("Received feedback")
        self._feedback = True

    def _wait_for_result_and_get(self, timeout=None):
        execute_timeout = rospy.Duration(timeout) if timeout else rospy.Duration(10)
        preempt_timeout = rospy.Duration(1)

        while not self._client.wait_for_result(execute_timeout):
            if not self._feedback:
                # preempt action
                rospy.logdebug("Canceling goal")
                self._client.cancel_goal()
                if self._client.wait_for_result(preempt_timeout):
                    rospy.loginfo("Preempt finished within specified preempt_timeout [%.2f]", preempt_timeout.to_sec());
                else:
                    rospy.logwarn("Preempt didn't finish specified preempt_timeout [%.2f]", preempt_timeout.to_sec());
                break
            else:
                self._feedback = False
                rospy.loginfo("I received feedback, let's wait another %.2f seconds" % execute_timeout.to_sec())

        state = self._client.get_state()
        if state != GoalStatus.SUCCEEDED:
            if state == GoalStatus.PREEMPTED:
                # Timeout
                _print_timeout()
                raise TimeoutException("Goal did not succeed within the time limit")
            else:
                _print_generic_failure()
                raise Exception("Goal did not succeed, it was: %s" % GoalStatus.to_string(state))

        return self._client.get_result()

    def _send_query(self, description, example_sentences, grammar, target):
        goal = QueryGoal(description=description, example_sentences=example_sentences, grammar=grammar, target=target)
        self._client.send_goal(goal, feedback_cb=self._feedback_callback)

    def query(self, description, grammar, target, timeout=10):
        """
        Perform a HMI query, returns a HMIResult
        """
        rospy.loginfo('Question: %s, grammar: %s', description, _truncate(grammar))

        # Verify the incoming grammar
        verify_grammar(grammar, target)

        example_sentences = random_sentences(grammar, target, 10)
        _print_example(random.choice(example_sentences))

        self._send_query(description, example_sentences, grammar, target)
        answer = self._wait_for_result_and_get(timeout=timeout)

        self.last_talker_id = answer.talker_id  # Keep track of the last talker_id

        result = result_from_ros(answer, grammar, target)
        _print_result(result)
        return result
