#!/usr/bin/env python

from hmi import AbstractHMIServer
from hmi_msgs.msg import QueryResult
from nose.tools import raises


result_set = False
aborted_set = False

def test_valid_server():
    global result_set
    result_set = False

    class HMIServer(AbstractHMIServer):
        def __init__(self):
            self._server = lambda: None
            self._server.is_preempt_requested = None

        def _determine_answer(self, description, example_sentences, grammar, target, is_preempt_requested):
            return QueryResult()

        def _set_succeeded(self, result):
            global result_set
            result_set = True

    server = HMIServer()

    from hmi_msgs.msg import QueryGoal
    goal = QueryGoal(description='q', grammar='g', target='t')

    assert not result_set
    server._execute_cb(goal)
    assert result_set


def test_valid_cancel():
    global result_set, aborted_set
    result_set = False

    class HMIServer(AbstractHMIServer):
        def __init__(self):
            self._server = lambda: None
            self._server.is_preempt_requested = None

        def _determine_answer(self, description, grammar, target, is_preempt_requested):
            return None

        def _set_aborted(self, text):
            global result_set
            result_set = True

    server = HMIServer()

    from hmi_msgs.msg import QueryGoal
    goal = QueryGoal(description='q', grammar='g', target='t')

    assert not result_set
    server._execute_cb(goal)
    assert result_set


@raises(TypeError)
def test_invalid_server():
    class HMIServer(AbstractHMIServer):
        def __init__(self):
            pass

    server = HMIServer()
