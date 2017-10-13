#! /usr/bin/python
# -*- coding: utf-8 -*-
# ----------------------------------------------------------------------------------------------------

"""Grammars for the ContextFreeGrammarParser are built from production rules, corresponding to the Rule-class below.
This means that sentences can be generated (and auto-completed), according to this grammar.
Moreover, sentences can be parsed according to the same rules.

See https://www.tutorialspoint.com/automata_theory/context_free_grammar_introduction.htm and
https://en.wikipedia.org/wiki/Context-free_grammar for an introduction to context free grammars.

If there is a rule "A -> one", then that means that to generate something according to rule A, the generated sentence is
"one"
In this example "A" is the lname. lname stands for left name, as it's on the left of the arrow.
Sentences are produced and parsed from left to right.

There can be multiple lines in the grammar definition file with the same lname, which simply add ways to produce/parse
sentences for that lname.

Rules can refer to each other via their lname.
If a rule A defines a way to start a sentence and refers to B, that means the completion of rule A is one via rule B.
For example, the grammar:
A -> go B
B -> forward
B -> backward
can generate the sentences "go forward" and "go backward". And thus parse these sentences as well.

Rules can also have variables that will be assigned to when a sentence is parsed.
For example, the line:

    VP["action": A] -> V_PLACE[A]

adds a rule for the lname VP, with a field called "action", which will be set to A.
The value for A is determined by a rule with lname V_PLACE, which will determine the value of A.

The rule

    V_PLACE["place"] -> place | put

applies when the text is "place" or "put".
When that is the case, the rule applies and the text "place" is filled in for A.
That means when the text "put" is typed, the variable "action" will be assigned the value "place".

The whole grammar has an entry point, or root rule, from which all the other rules are referred.
Each rule forms branch upon branch, together building a Tree.

When a sentence is parsed, a Tree is built. While this happens, the variables are collected.
When the Tree is completely parsed, the collected variables and their assignments are fetched from the Tree with the get_semantics-method.
This returns a string. However, this string represents a (nested) dictionary that maps a variable to a value.

Semantics describe what a sentence means. In this case, it describes what action to perform and with what to perform it.
"""
import random
import re
import yaml
from yaml import MarkedYAMLError
import itertools


class Alternative:
    def __init__(self, values=[]):
        self.values = values

    def __repr__(self):
        return "Alternative({})".format(self.values)


class Sequence:
    def __init__(self, values=[]):
        self.values = values

    def __repr__(self):
        return "Sequence({})".format(self.values)


class Option:
    """An option is a continuation of a sentence of where there are multiple ways to continue the sentence.
    These choices in an Option are called called conjuncts."""

    def __init__(self, lsemantic="", conjs=None):
        """Constructor of an Option
        :param lsemantic the name of the semantics that the option is the continuation of. E.g. if the lsemantic is some action, this option might be the object to perform that action with.
        :param conjs the choices in this option"""
        self.lsemantic = lsemantic
        if conjs:
            self.conjuncts = conjs
        else:
            self.conjuncts = []

    def __repr__(self):
        return "Option(lsemantic='{lsem}', conjs={c})".format(lsem=self.lsemantic, c=self.conjuncts)

    def __eq__(self, other):
        if isinstance(other, Option):
            return self.lsemantic == other.lsemantic and self.conjuncts == other.conjuncts

        return False

    @staticmethod
    def from_cfg_def(option_definition, left_semantics):
        """Parse text from the CFG definition into an Option and the choices it is composed of. """
        opt_strs = option_definition.split("|")

        for opt_str in opt_strs:
            opt_str = opt_str.strip()

            opt = Option(left_semantics)

            while opt_str:
                (rname, rsem, opt_str) = parse_next_atom(opt_str)
                is_variable = rname[0].isupper()
                opt.conjuncts += [Conjunct(rname, rsem, is_variable)]

            yield opt


# ----------------------------------------------------------------------------------------------------


class Conjunct:
    """"A Conjunct is a placeholder in the parse-tree, which can be filled in by an Option or a word"""

    def __init__(self, name, rsemantic="", is_variable=False):
        """:param name the word or variable
        :param rsemantic what option is the Conjunct part of
        :param is_variable is the conjunct variable or terminal?"""
        self.name = name
        self.rsemantic = rsemantic
        self.is_variable = is_variable

    def __repr__(self):
        return "Conjunct(name='{name}', rsemantic='{r}', is_variable={v})".format(name=self.name, r=self.rsemantic,
                                                                                  v=self.is_variable)

    def __eq__(self, other):
        if isinstance(other, Conjunct):
            return self.name == other.name and \
                   self.rsemantic == other.rsemantic and \
                   self.is_variable == other.is_variable
        return False


# ----------------------------------------------------------------------------------------------------


class Rule:
    def __init__(self, lname, options=None):
        self.lname = lname
        self.options = options if options else []

    def __repr__(self):
        return "Rule(lname='{lname}', options={opts})".format(lname=self.lname, opts=self.options)

    def __eq__(self, other):
        if isinstance(other, Rule):
            return self.lname == other.lname and self.options == other.options

        return False

    @staticmethod
    def from_cfg_def(s):
        tmp = s.split(" -> ")
        if len(tmp) != 2:
            raise Exception("Invalid grammar, please use proper ' -> ' arrows", tmp)

        (lname, lsem, outstr) = parse_next_atom(tmp[0].strip())

        rule = Rule(lname)

        rule.options = list(Option.from_cfg_def(tmp[1], lsem))

        return rule


# ----------------------------------------------------------------------------------------------------


class Tree:
    def __init__(self, option):
        self.option = option
        self.subtrees = [None for c in self.option.conjuncts]
        self.parent = None
        self.parent_idx = 0

    def next(self, idx):
        if idx + 1 < len(self.option.conjuncts):
            return self, idx + 1
        else:
            if self.parent:
                return self.parent.next(self.parent_idx)
            else:
                return None, 0

    def add_subtree(self, idx, tree):
        tree.parent = self
        tree.parent_idx = idx
        self.subtrees[idx] = tree
        return tree

    def __repr__(self):
        # TODO: Make this print like a tree
        return str(zip(self.option.conjuncts, self.subtrees))


# ----------------------------------------------------------------------------------------------------


def parse_next_atom(s):
    """
    Returns (name, semantics, remaining_str)
    For example for "VP[X, Y] foo bar" it returns:
         ("VP", "X, Y", "foo bar")
    :param s:
    :return: Tuple with the rule's lname, the variables involved and the remaining text: ("VP", "X, Y", "foo bar")
    """
    s = s.strip()

    for i in range(0, len(s)):
        c = s[i]
        if c == ' ':
            return s[:i], "", s[i:].strip()
        elif c == '[':
            j = s.find("]", i)
            if j < 0:
                raise Exception
            return s[:i], s[i + 1:j], s[j + 1:].strip()

    return s, "", ""


# ----------------------------------------------------------------------------------------------------


class GrammarParser:
    def __init__(self):
        self.rules = {}
        self.functions = {}

    @staticmethod
    def fromfile(filename):
        with open(filename) as f:
            string = f.read()
        return GrammarParser.fromstring(string)

    @staticmethod
    def fromstring(string):
        parser = GrammarParser()
        for line in string.replace(";", "\n").split("\n"):
            line = line.strip()
            if line == "" or line[0] == '#':
                continue
            parser.add_rule(line)

        return parser

    def verify(self, target=None):
        if target is None:
            # Try whether all rules in the grammar are valid
            for r in self.rules:
                self.get_tree(r)
        else:
            self.get_tree(target)
        return True

    def add_rule(self, s):
        rule = Rule.from_cfg_def(s)

        # See if a rule with this lname already exists. If not, add it
        if rule.lname in self.rules:
            original_rule = self.rules[rule.lname]
            original_rule.options += rule.options
        else:
            self.rules[rule.lname] = rule

    def set_function(self, name, func):
        self.functions[name] = func

    def get_semantics(self, tree):
        """Get the semantics of a tree.
        This means that variables are unified with their values, which may be recursively gotten from the tree's subtrees. """
        semantics = tree.option.lsemantic
        for i in range(0, len(tree.subtrees)):
            conj = tree.option.conjuncts[i]
            subtree = tree.subtrees[i]

            if subtree:
                child_semantics = self.get_semantics(subtree)
                semantics = semantics.replace(conj.rsemantic, child_semantics)

        return semantics

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

    def parse(self, target, words, debug=False):
        if isinstance(words, basestring):
            words = words.split(" ")

        if not target in self.rules:
            raise Exception("Target {} not present in grammar rules".format(target))

        rule = self.rules[target]

        for opt in rule.options:
            T = Tree(opt)
            if self._parse((T, 0), words):
                # Simply take the first tree that successfully parses
                semantics_str = self.get_semantics(T).replace("<", "[").replace(">", "]")
                try:
                    semantics = yaml.safe_load(semantics_str)
                except MarkedYAMLError as e:
                    raise Exception("Failed to parse semantics", semantics_str, e)
                return semantics

        return False

    def _parse(self, T_idx, words):
        (T, idx) = T_idx

        if not T:
            return words == []

        if not words:
            return False

        conj = T.option.conjuncts[idx]

        if conj.is_variable:
            if conj.name not in self.rules:
                return False
            options = self.rules[conj.name].options

        elif conj.name[0] == "$":
            func_name = conj.name[1:]
            if not func_name in self.functions:
                return False
            options = self.functions[func_name](words)

        else:
            if conj.name == words[0]:
                return self._parse(T.next(idx), words[1:])
            else:
                return False

        for opt in options:
            subtree = T.add_subtree(idx, Tree(opt))
            ret = self._parse((subtree, 0), words)
            if ret:
                return ret

        return False

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

    def get_tree(self, lname):
        if lname not in self.rules:
            raise Exception("Target {} not present in grammar rules".format(lname))

        rule = self.rules[lname]

        alternative_values = []
        for opt in rule.options:
            sequence_values = []

            for conj in opt.conjuncts:
                if conj.is_variable:
                    tree = self.get_tree(conj.name)
                    if tree:
                        sequence_values.append(tree)
                else:
                    sequence_values.append(conj.name)

            alternative_values.append(Sequence(sequence_values))

        return Alternative(alternative_values)

    @staticmethod
    def _get_all_sentences_from_tree(node, max_sentences):
        """

        :param node: Node to expand to generate sentences
        :param max_sentences: Maximum allowed number of sentences (to avoid high calculation times)
        :return: List of all possible sentences in the given grammar

        TODO: Reuse previously expanded rules to reduce number of expanded nodes.
        E.g. {node1: string_list1, ...} and do a lookup before expanding
        """
        if isinstance(node, Alternative):
            string_list = []
            for value in node.values:
                res = GrammarParser._get_all_sentences_from_tree(value, max_sentences)
                string_list += res
        elif isinstance(node, Sequence):
            string_list = []
            for value in node.values:
                res = GrammarParser._get_all_sentences_from_tree(value, max_sentences)
                if string_list:
                    string_list = [" ".join(e) for e in itertools.product(string_list, res)]
                else:
                    string_list = res
        elif isinstance(node, str):
            string_list = [node]
        if len(string_list) > max_sentences:
            raise Exception("Too many options in grammar.")
        return string_list

    @staticmethod
    def _get_random_sentence_from_tree(node):
        """
        :param node: Node to expand to generate sentences
        :return: A randomly generated sentence according to the given node
        """
        sentence = ""
        if isinstance(node, Alternative):
            sentence = GrammarParser._get_random_sentence_from_tree(random.choice(node.values))
        elif isinstance(node, Sequence):
            word_list = []
            for value in node.values:
                word_list.append(GrammarParser._get_random_sentence_from_tree(value))
            sentence = " ".join(word_list)
        elif isinstance(node, str):
            sentence = node
        return sentence

    def get_random_sentences(self, lname, num):
        tree = self.get_tree(lname)

        try:
            sentences = self._get_all_sentences_from_tree(tree, 1e5)
            random.shuffle(sentences)
            sentences = sentences[:num]
        except:
            sentences = [self._get_random_sentence_from_tree(tree) for _ in range(0, num)]

        return sentences

    # - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

    def to_bnf_grammar(self, lname):
        """
        Generate Nuance BNF Format grammar from the grammar used by hmi
        :param lname: The root
        :return: BNF String
        """
        bfn_rule_dict = {}
        for name, rule in self.rules.iteritems():
            bfn_rule_dict[rule.lname] = " | ".join([" ".join("<" + c.name + ">"
                                                             if c.is_variable else c.name
                                                             for c in option.conjuncts) for option in rule.options])

        string = '#BNF+EMV1.1;\n!grammar "BNFEnglish";\n!start <{}>;\n'.format(lname)
        for k, v in bfn_rule_dict.iteritems():
            string += "<{}>: {};\n".format(k, v)

        return string
