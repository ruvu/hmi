#!/usr/bin/env python
import traceback
from abc import ABCMeta, abstractmethod

import rospy
from actionlib import SimpleActionServer
from hmi_msgs.msg import QueryAction, QueryActionFeedback

from .common import trim_string, result_to_ros


class AbstractHMIServer(object):
    """
    Abstract base class for a hmi servers

    """
    __metaclass__ = ABCMeta

    def __init__(self, name):
        self._server = SimpleActionServer(name, QueryAction,
                                          execute_cb=self._execute_cb, auto_start=False)
        self._server.start()
        rospy.loginfo('HMI server started on "%s"', name)

    def _execute_cb(self, goal):
        rospy.loginfo('I got a question: %s', goal.description)
        rospy.loginfo('This is the grammar: %s, %s', trim_string(goal.grammar), goal.target)

        try:
            result = self._determine_answer(description=goal.description,
                                            example_sentences=goal.example_sentences,
                                            grammar=goal.grammar,
                                            target=goal.target,
                                            is_preempt_requested=self._is_preempt_requested)
        except Exception as e:
            tb = traceback.format_exc()
            rospy.logerr('_determine_answer raised an exception: %s' % tb)

            self._set_aborted()
        else:
            # we've got a result or a cancel
            if result:
                rospy.loginfo('result: %s', result)
                self._set_succeeded(result=result_to_ros(result))
            else:
                msg = "Cancelled by user"
                rospy.loginfo(msg)
                self._set_aborted(text=msg)

    def _set_succeeded(self, result):
        self._server.set_succeeded(result)

    def _set_aborted(self, text=""):
        self._server.set_aborted(text=text)

    def _publish_feedback(self):
        self._server.publish_feedback(QueryActionFeedback())

    def _is_preempt_requested(self):
        return self._server.is_preempt_requested()

    @abstractmethod
    def _determine_answer(self, description, grammar, target, is_preempt_requested):
        """
        Overwrite this method to provide custom implementations

        Return the answer
        Return None if nothing is heared
        Raise an Exception if an error occured
        """
        pass
