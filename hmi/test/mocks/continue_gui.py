#!/usr/bin/python

import sys
import math

# ROS
import rospy

# Qt
import signal
from python_qt_binding import QtGui
from python_qt_binding import QtCore

# TU/e
from hmi.abstract_server import HMIResult, AbstractHMIServer

from cfgparser import CFGParser

# -----------------------------------------------------------------------------

class UpdateThread(QtCore.QThread):
    """ Update thread """
    description = QtCore.pyqtSignal(['QString'])
    spec = QtCore.pyqtSignal(['QString'])
    key = QtCore.pyqtSignal(['QString'])
    buttons = QtCore.pyqtSignal(['QString'])  # String, buttons separated by ;
    valid = QtCore.pyqtSignal([bool])

    def __init__(self, gui, server):
        """ Constructor

        :param gui: GUI where things are displayed
        :param server: hmi server interface
        """
        super(UpdateThread, self).__init__()
        print "Thread init"
        self._gui = gui
        self._server = server

        self._description = ""
        self._spec = ""
        self._buttons = ""
        self._key = ""
        self._valid = False
        self._submit = False
        self._current_text = ""

    def run(self):

        print "Thread.run"
        r = rospy.Rate(5)
        while not rospy.is_shutdown():
            # question, buttons = self._server.update(self._current_text)
            res = self._server.update(current_text=self._current_text, submit=self._submit)

            # if question and question != self.question:
            if res.description != self._description:
                self.description.emit(res.description)
                self._description = res.description
            if res.key != self._key:
                self.key.emit(res.key)
                self._key = res.key
            if res.spec != self._spec:
                self.spec.emit(res.spec)
                self._spec = res.spec
            buttonstr = ""
            for b in res.buttons:
                buttonstr += (b + ";")
            if buttonstr != self._buttons:
                self.buttons.emit(buttonstr)
                self._buttons = buttonstr
            if res.valid != self._valid:
                self.valid.emit(res.valid)
                self._valid = res.valid
            self._submit = False  # Reset submit button
            r.sleep()

    def set_text(self, text):
        """ Sets the text to use in the update loop of the HMI server
        :param text: text to set
        """
        self._current_text = str(text)

    def submit(self):
        """ Slot for the submit button of the GUI
        """
        self._submit = True


# -----------------------------------------------------------------------------


class GuiMode(object):
    RESULT_PENDING = -1
    IDLE = 0
    SIMPLE_QUESTION = 1
    USE_GRAMMAR = 2


# -----------------------------------------------------------------------------


class UpdateResult(object):
    """ Return value of the update function of the HMIServerGuiInterface """
    def __init__(self, description="", spec="", key="", buttons=[], isvalid=False):
        """ Constructor

        :param description: asked question ("Which <fruit> would you like")
        :param spec: spec ("I would like <fruit>")
        :param key: part of the answer we are answering  ("<fruit>")
        :param buttons: possible buttons to click (["banana", "apple"])
        :param isvalid: bool indicating whether the current text is valid
        """
        self.description = description
        self.spec = spec
        self.key = key
        self.buttons = buttons
        self.valid = isvalid

    def __repr__(self):
        return "Description: {0}\nSpec: {1}\nKey: {2}\nButtons: {3}".format(self.description, self.spec,
                                                                            self.key, self.buttons)


# -----------------------------------------------------------------------------


class HMIServerGUIInterface(AbstractHMIServer):
    """ Provides the HMI server within the ContinueGUI. Contains '_determine_answer'
    only sets the goal. An 'update' function, that must be called in a loop, does
    the actual work
    """
    def __init__(self, name, grammar_filename=None):
        """ Constructor
        :param name: ???
        """
        super(HMIServerGUIInterface, self).__init__(name)

        self._description = ""
        self._choices = {}
        self._spec = ""
        self._is_preempt_requested = False

        self._mode = GuiMode.IDLE

        self._result = None  # HMIResult(results=results)

        # For simple questions
        self._simple_question_index = 0
        self._results_dict = {}

        # For grammars
        self._current_text = ""

        if grammar_filename:
            self.parser = CFGParser.fromfile(grammar_filename)
        else:
            self.parser = None

        # To check if we need to publish feedback
        self._latest_text = ""

    def _determine_answer(self, description, example_sentences, spec, choices, is_preempt_requested):
        """
        Sets some members and blocks until we can either an answer is created
        or the goal is cancelled

        Return the answer
        Return None if nothing is heared
        Raise an Exception if an error occured
        """
        self._description = description
        self._spec = spec
        self._choices = choices
        self._is_preempt_requested = is_preempt_requested

        if len(self._spec) < 200:
            self._mode = GuiMode.SIMPLE_QUESTION
            self._simple_question_index = 0
            self._results_dict = {}
        else:
            self._mode = GuiMode.USE_GRAMMAR

        print "Received HMI request"
        r = rospy.Rate(5.0)
        while self._mode != GuiMode.RESULT_PENDING:  # and not is_preempt_requested()
            if is_preempt_requested() or rospy.is_shutdown():
                break
            # print "Checking result, mode: {0}, preempt requested: {1}".format(self._mode, is_preempt_requested())
            r.sleep()

        self._mode = GuiMode.IDLE

        print "Yeah, we're done, result: {0}".format(self._results_dict)
        return self._result

    def _get_word_options(self, words):
        """ Returns the possible options that can follow on the provided sequence of words.

        :param words: list of words of the currently provided text
        :return: list with possibilities
        """
        options = list(set(self.parser.next_word("T", words)))

        new_options = []

        for opt in options:
            next_words = words + [opt]

            while True:
                next_options = list(set(self.parser.next_word("T", next_words)))

                if len(next_options) != 1 or self._is_valid_sentence(next_words):
                    break

                next_words += [next_options[0]]
                opt += " {}".format(next_options[0])
            new_options.append(opt)

        return new_options

    def _is_valid_sentence(self, words):
        """ Checks if the current list of words is valid as an assignment for the robot

        :param words: list of words of the currently provided text
        :return: bool whether this the words are a valid command
        """

        if self.parser.parse("T", words):
            return True
        else:
            return False

    def update(self, current_text, submit=False):
        """ Continuously updates

        :param current_text: current text of the GUI textbox
        :param submit: bool indicating whether the submit button has been pressed
        :return: tuple with a question (optionally) and a list with the possible words. If the list is empty,
        there is no current goal any more
        """

        if self._latest_text is not current_text:
            self._latest_text = current_text
            self._publish_feedback()

        # If idle: return
        if self._mode in [GuiMode.IDLE, GuiMode.RESULT_PENDING]:
            return UpdateResult(description="", spec="", key="", buttons=[], isvalid=False)

        # If simple question: check if answered
        if self._mode == GuiMode.SIMPLE_QUESTION:
            k = self._choices.keys()[self._simple_question_index]
            v = self._choices[k]

            if submit:
                self._results_dict[k] = self._current_text
                self._current_text = ""
                self._simple_question_index += 1
                if len(self._choices) == self._simple_question_index:
                    self._result = HMIResult(results=self._results_dict)
                    self._mode = GuiMode.RESULT_PENDING
                    return UpdateResult(description="", spec="", key="", buttons=[], isvalid=False)
                else:
                    return UpdateResult(description=self._description, spec=self._spec, key="", buttons=[],
                                        isvalid=False)
            else:
                if current_text in v:
                    buttons = []
                    self._current_text = current_text  # Store the current text
                else:
                    buttons = v
                return UpdateResult(description=self._description, spec=self._spec, key=k, buttons=buttons,
                                    isvalid=(current_text in v))

        # If grammar: check parser
        if self._mode == GuiMode.USE_GRAMMAR:
            if not self.parser:
                return UpdateResult(description=self._description, spec="", key="", buttons=[], isvalid=False)
            elif submit:

                # post-process the given text

                filtered_text = self._current_text
                num_ands = filtered_text.count(" and ")
                if num_ands > 1:
                    filtered_text = filtered_text.replace(" and", "", num_ands - 1)

                filtered_text = filtered_text.replace("bookcase", "bocase")
                filtered_text = filtered_text.replace("_", " ")


                self._result = HMIResult(filtered_text)  # The stored value is returned to make sure the
                # text did not change between the check and clicking the 'Submit' button
                self._mode = GuiMode.RESULT_PENDING
                return UpdateResult(description="", spec="", key="", buttons=[],
                                    isvalid=False)
            else:
                if not current_text:
                    words = []
                else:
                    words = current_text.strip().split(' ')

                options = sorted(self._get_word_options(words))
                valid = self._is_valid_sentence(words)

                self._current_text = current_text  # Store the current text
                return UpdateResult(description=self._description, spec="", key="", buttons=options, isvalid=valid)

        return UpdateResult(description="", spec="", key="", buttons=[], isvalid=False)


# -----------------------------------------------------------------------------


class ButtonCB(object):
    """ Helper object to dynamically create callback functions """
    def __init__(self, parent, text):
        self._parent = parent
        self._text = text

    def callback(self):
        self._parent.add_to_textbox(self._text)


# -----------------------------------------------------------------------------


class ContinueGui(QtGui.QWidget):
    """
    GUI for the RoboCup continue rule
    """
    current_text = QtCore.pyqtSignal(['QString'])   # Necessary to emit current text to update thread

    def __init__(self, grammar_filename=None):
        """ Constructor """
        super(ContinueGui, self).__init__()

        self.resize(640, 480)
        self.move(300, 300)
        self.setWindowTitle('Continue GUI')

        # Add the description box
        self.description_label = QtGui.QLabel(self)
        self.description_label.setMaximumHeight(100)

        # Add the question box
        self.spec_label = QtGui.QLabel(self)
        self.spec_label.setMaximumHeight(100)

        # Add the key box
        self.key_label = QtGui.QLabel(self)
        self.key_label.setMaximumHeight(100)

        # Add the texteditbox
        self.textbox = QtGui.QTextEdit(self)
        self.textbox.textChanged.connect(self._text_changed)

        # Add the submit button
        self.submit_button = QtGui.QPushButton(self)
        self.submit_button.setText("Submit")
        self.submit_button.setEnabled(False)

        # Add the clear button
        self.clear_button = QtGui.QPushButton(self)
        self.clear_button.setText("Clear")

        # Submit/clear button layout
        self.submit_clear_button_layout = QtGui.QVBoxLayout()
        self.submit_clear_button_layout.addWidget(self.submit_button)
        self.submit_clear_button_layout.addWidget(self.clear_button)
        self.submit_clear_button_widget = QtGui.QWidget()
        self.submit_clear_button_widget.setLayout(self.submit_clear_button_layout)

        # Add the QButtonGroup
        # self.option_buttons = QtGui.QButtonGroup(self) (ToDo: how can I do this nicely???)
        # self.button_layout = QtGui.QVBoxLayout()
        self.button_layout = QtGui.QGridLayout()
        self.button_widget = QtGui.QWidget()
        self.button_widget.setLayout(self.button_layout)
        self.button_widget.setSizePolicy(2, 2)  # Makes sure we don't get enormous buttons

        # Top layout
        self._top_layout = QtGui.QHBoxLayout(self)
        self._top_layout.addWidget(self.textbox)
        self._top_layout.addWidget(self.submit_clear_button_widget)
        self._top_widget = QtGui.QWidget()
        self._top_widget.setLayout(self._top_layout)
        self._top_widget.setMaximumHeight(100)

        # Main layout
        self._main_layout = QtGui.QVBoxLayout(self)
        self._main_layout.addWidget(self.description_label)
        self._main_layout.addWidget(self.spec_label)
        self._main_layout.addWidget(self.key_label)
        self._main_layout.addWidget(self._top_widget)
        # self._main_layout.addWidget(self.option_buttons)
        self._main_layout.addWidget(self.button_widget)
        self._main_layout.insertStretch(-1, 0)

        # List with ButtonCBs
        self._button_cbs = []

        # Setup the interface
        self.server_interface = HMIServerGUIInterface('continui', grammar_filename)

        # Update thread
        self.update_thread = UpdateThread(self, self.server_interface)
        self.update_thread.buttons.connect(self.buttons_callback)
        self.update_thread.description.connect(self.description_callback)
        self.update_thread.spec.connect(self.spec_callback)
        self.update_thread.key.connect(self.key_callback)
        self.update_thread.valid.connect(self.valid_callback)
        self.current_text.connect(self.update_thread.set_text)
        self.submit_button.clicked.connect(self.update_thread.submit)
        self.submit_button.clicked.connect(self.clear_text)
        self.clear_button.clicked.connect(self.clear_text)
        self.update_thread.start()

        self.show()

    def _clear_clicked(self):
        print "bla"

    def _text_changed(self):
        """ Callback function if text in the textbox has changed. Gets the text and emits
        this as a signal
        """
        text = self.textbox.toPlainText()
        self.current_text.emit(text)

    def description_callback(self, text):
        """ Puts the provided text in the label
        :param text: string with text
        """
        self.description_label.setText(text)

    def key_callback(self, text):
        """ Puts the provided text in the label
        :param text: string with text
        """
        self.key_label.setText(text)

    def spec_callback(self, text):
        """ Puts the provided text in the label
        :param text: string with text
        """
        self.spec_label.setText(text)

    def valid_callback(self, valid):
        """ Sets the 'Submit' button to enabled/disabled based on the valid
        :param valid: bool whether this is valid
        """
        self.submit_button.setEnabled(valid)

    def add_to_textbox(self, text):
        """ Adds the text to the textbox, taking spaces into account

        :param text: text to add
        :return:
        """
        current_text = self.textbox.toPlainText()
        if current_text == "":
            self.textbox.insertPlainText(text)
        else:
            self.textbox.insertPlainText(" "+text)

    def buttons_callback(self, buttons):
        """ PyQt slot for buttons to add. Buttons are always cleared beforehand
        :param buttons: QString containing the text of the buttons to add, separated by ';'
        """
        # Start by clearing
        self.clear_buttons()

        # If we don't have to add anything, return
        if not buttons:
            return

        start = rospy.Time.now()

        # We want a maximum of 160 characters on one line. This means one word can have up to 160/5=32 characters
        # If this is exceeded, we will scale accordingly
        buttonlist = buttons.split(';')
        max_length = len(buttonlist[0])
        for b in buttonlist:
            if len(b) > max_length:
                max_length = len(b)
        factor = 32.0/max_length
        nr_cols = min(5, max(1, math.floor(factor * 5)))
        nr_rows = math.ceil(len(buttons)/float(nr_cols))

        row = 0
        col = 0
        for b in str(buttons).split(';'):
            self.add_button(b, row, col)
            col += 1
            if col == nr_cols:
                col = 0
                row += 1
        rospy.loginfo("Adding buttons took {0} seconds".format((rospy.Time.now() - start).to_sec()))

    def add_button(self, text, row, col):
        """ Adds a button with an option to the GUI
        :param text: text of the button to add
        :param row: row where to add the button
        :param col: column where to add the button
        """
        if text == "":
            return
            # self.clear_buttons()

        b = QtGui.QPushButton()
        b.setText(text.replace("_", " "))

        bcb = ButtonCB(self, text)
        self._button_cbs.append(bcb)
        self.button_layout.addWidget(b, row, col)
        b.clicked.connect(bcb.callback)

    def clear_buttons(self):
        """ Removes all option buttons """
        # Remove all buttons
        while True:
            b = self.button_layout.takeAt(0)
            if b is None:
                break
            else:
                b.widget().setParent(None)

        # Clear the list with callbacks
        self._button_cbs = []

    def clear_text(self):
        """ Clears the text from the textbox """
        self.textbox.setText("")

    def closeEvent(self, event):
        rospy.loginfo('Close event received')
        rospy.signal_shutdown('close event')


if __name__ == '__main__':

    rospy.init_node('continue_gui', anonymous=True)

    app = QtGui.QApplication(sys.argv)
    timer = QtCore.QTimer()
    timer.start(500)
    timer.timeout.connect(lambda: None) # wake up python every now and again

    # also close Qt when a Ctrl+C is pressed
    def handleIntSignal(signum, frame):
        rospy.loginfo('close all windows')
        app.closeAllWindows()
    signal.signal(signal.SIGINT, handleIntSignal)

    if len(sys.argv) > 1 and sys.argv[1][0] != '_':
        grammar_filename = sys.argv[1]
    else:
        grammar_filename = None

    w = ContinueGui(grammar_filename=grammar_filename)
    #w = ContinueGui()

    sys.exit(app.exec_())
