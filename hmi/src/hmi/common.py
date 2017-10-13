#!/usr/bin/env python
import json
import random
import re
from collections import namedtuple

import rospy
from hmi_msgs.msg import QueryResult

HMIResult = namedtuple('HMIResult', ['sentence', 'semantics'])
from hmi.grammar_parser import GrammarParser


def result_to_ros(result):
    return QueryResult(
        talker_id='',
        sentence=result.sentence,
        semantics=json.dumps(result.semantics)
    )


def result_from_ros(msg):
    return HMIResult(sentence=msg.sentence, semantics=json.loads(msg.semantics))


def trim_string(data, max_length=75, ellipsis='...'):
    l = max_length - len(ellipsis)
    return (data[:l] + ellipsis) if len(data) > l else data


def verify_grammar(grammar, target=None):
    grammar_parser = GrammarParser.fromstring(grammar)
    grammar_parser.verify(target)


def random_sentences(grammar, target, num):
    grammar_parser = GrammarParser.fromstring(grammar)
    grammar_parser.verify()
    return grammar_parser.get_random_sentences(target, num)


def parse_sentence(sentence, grammar, target):
    grammar_parser = GrammarParser.fromstring(grammar)
    return grammar_parser.parse(target, sentence)
