#!/usr/bin/env python
from collections import namedtuple

import rospy
from actionlib import SimpleActionClient, GoalStatus
from dragonfly_speech_recognition.srv import GetSpeechResponse
from hmi.common import random_fold_spec, result_from_ros
from hmi_msgs.msg import QueryAction, QueryGoal


class TimeoutException(Exception):
    pass


OldSpeechResponse = namedtuple('OldSpeechResponse', ['result', 'choices'])


def _truncate(data):
    return (data[:75] + '..') if len(data) > 75 else data


def _print_example(grammar, target):
    # TODO: Reimplement random_fold_spec with the grammar parser
    return
    grammar = random_fold_spec(grammar, target)
    rospy.loginfo("Example: \x1b[1;44m'{}'\x1b[0m".format(grammar.strip()))


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

    def _send_query(self, description, grammar, target):
        goal = QueryGoal(description=description, grammar=grammar, target=target)
        self._client.send_goal(goal, feedback_cb=self._feedback_callback)

    def query(self, description, grammar, target, timeout=10):
        """
        Perform a HMI query, returns a HMIResult
        """
        rospy.loginfo('Question: %s, grammar: %s', description, _truncate(grammar))
        _print_example(grammar, target)

        self._send_query(description, grammar, target)
        answer = self._wait_for_result_and_get(timeout=timeout)

        self.last_talker_id = answer.talker_id  # Keep track of the last talker_id

        result = result_from_ros(answer)
        _print_result(result)
        return result

    def old_query(self, spec, choices, timeout=10):
        """
        Convert old queries to a HMI query
        """
        rospy.loginfo('spec: %s', _truncate(spec))

        # convert old spec to new spec
        grammar = 'T -> ' + spec
        for choice, values in choices.items():
            grammar = grammar.replace('<%s>' % choice, choice.upper())
            for value in values:
                grammar += '; %s[{%s: %s}] -> %s' % (choice.upper(), choice, value, value)

        target = 'T'

        rospy.loginfo('grammar: %s', _truncate(grammar))
        _print_example(grammar, target)

        self._send_query('', grammar, target)
        try:
            answer = self._wait_for_result_and_get(timeout=timeout)
        except TimeoutException:
            return OldSpeechResponse(result="")
        except:
            return None
        else:
            # so we've got an answer
            self.last_talker_id = answer.talker_id  # Keep track of the last talker_id

            result = result_from_ros(answer)
            _print_result(result)

            return OldSpeechResponse(result=result.sentence, choices=result.semantics)
