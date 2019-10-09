# *****************************************************************
#
# Licensed Materials - Property of IBM
#
# (C) Copyright IBM Corp. 2018. All Rights Reserved.
#
# US Government Users Restricted Rights - Use, duplication or
# disclosure restricted by GSA ADP Schedule Contract with IBM Corp.
#
# *****************************************************************

import io
import json
import logging
import os
import shlex
import subprocess
import sys
import unittest
import re

# Put the local module at the beginning of the path in case there's an installed
# copy on the system
local_module = os.path.realpath(os.path.join(os.path.dirname(__file__), '..', 'alog'))
sys.path = [local_module] + sys.path
import alog

# Note on log capture: In these tests, we could attach a stream capture handler,
# but logs captured that way will not include formatting, so that doesn't work
# for these tests. Instead, we run python subprocesses and capture the logging
# results.

def get_subproc_cmds(lines):
    commands_to_run = "python3 -c \"import alog;"
    for line in lines:
        commands_to_run += " %s;" % line
    commands_to_run += "\""
    return commands_to_run

def pretty_level_to_name(pretty_level):
    for name, pretty_name in alog.AlogPrettyFormatter._LEVEL_MAP.items():
        if pretty_name == pretty_level:
            return pretty_name
    return None

def parse_pretty_line(line):
    timestamp_regex = "([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}.[0-9]{6})"
    rest_of_regex = "\\[([^:]*):([^\\]:]*):?([0-9]*)\\]( ?<[^\s]*>)? ([\\s]*)([^\\s].*)\n?"
    whole_regex = "^%s %s$" % (timestamp_regex, rest_of_regex)
    expr = re.compile(whole_regex)
    match = expr.match(line.decode('utf-8'))
    assert match is not None
    res = {
        'timestamp': match[1],
        'channel': match[2].strip(),
        'level': pretty_level_to_name(match[3]),
        'num_indent': len(match[6]) / len(alog.AlogPrettyFormatter._INDENT),
        'message': match[7],
    }
    if len(match[4]) > 0:
        res['thread_id'] = int(match[4])
    if match[5] is not None:
        res['log_code'] = match[5].strip()
    return res

class TestJsonCompatibility(unittest.TestCase):
    '''Ensures that printed messages are valid json format when json formatting is specified'''

    def test_merge_msg_json(self):
        '''Tests that dict messages are merged when using json format. May be too complicated...'''
        # Set up the subprocess command
        commands_to_run = get_subproc_cmds([
            "alog.configure(default_level='info', filters='', formatter='json')",
            "test_channel = alog.use_channel('test_merge_msg_json')",
            "test_channel.info(dict({'test_msg':1}))",
        ])

        # run in subprocess and capture stderr
        _, stderr = subprocess.Popen(shlex.split(commands_to_run), stderr=subprocess.PIPE).communicate()
        logged_output = json.loads(stderr)

        self.assertIsNotNone(logged_output)
        self.assertIsInstance(logged_output, dict)

        for key in logged_output.keys():
            # should have merged all dict's!
            self.assertNotIsInstance(logged_output[key], dict)
        # key should be present if the message was merged into top-level dict
        self.assertIn('test_msg', logged_output)
        # value should be the same
        self.assertEqual(logged_output['test_msg'], 1)

    def test_empty_msg_json(self):
        '''Tests that logs are in json format with an empty message. May be too complicated...'''
        # Set up the subprocess command
        commands_to_run = get_subproc_cmds([
            "alog.configure(default_level='info', filters='', formatter='json')",
            "test_channel = alog.use_channel('test_merge_msg_json')",
            "test_channel.info('')",
        ])

        # run in subprocess and capture stderr
        _, stderr = subprocess.Popen(shlex.split(commands_to_run), stderr=subprocess.PIPE).communicate()
        logged_output = json.loads(stderr)

        self.assertIsInstance(logged_output, dict)

class TestCustomFormatter(unittest.TestCase):

    def test_pretty_with_args(self):
        '''Tests that a manually constructed AlogPrettyFormatter can be used'''
        alog.configure('info', '', formatter=alog.AlogPrettyFormatter(10))

class TestThreadId(unittest.TestCase):

    def test_thread_id_json(self):
        '''Test that the thread id is given with json formatting'''
        commands_to_run = get_subproc_cmds([
            "alog.configure(default_level='info', filters='', formatter='json', thread_id=True)",
            "test_channel = alog.use_channel('test_merge_msg_json')",
            "test_channel.info('This is a test')",
        ])

        # run in subprocess and capture stderr
        _, stderr = subprocess.Popen(shlex.split(commands_to_run), stderr=subprocess.PIPE).communicate()
        logged_output = json.loads(stderr)

        # Make sure the thread_id key is present
        self.assertIsInstance(logged_output, dict)
        self.assertIn('thread_id', logged_output)

    def test_thread_id_pretty(self):
        '''Test that the thread id is given with pretty formatting'''
        commands_to_run = get_subproc_cmds([
            "alog.configure(default_level='info', filters='', formatter='pretty', thread_id=True)",
            "test_channel = alog.use_channel('test_merge_msg_json')",
            "test_channel.info('This is a test')",
        ])

        # run in subprocess and capture stderr
        _, stderr = subprocess.Popen(shlex.split(commands_to_run), stderr=subprocess.PIPE).communicate()
        logged_output = [line for line in stderr.split(b'\n') if len(line) > 0]

        # Parse the line header
        self.assertEqual(len(logged_output), 1)
        line = logged_output[0]
        parts = parse_pretty_line(line)
        self.assertIn('thread_id', parts)

class TestLogCode(unittest.TestCase):

    def test_log_code_dict(self):
        '''Test that logging a dict with a log code and message adds the code to
        the header as expected
        '''
        commands_to_run = get_subproc_cmds([
            "alog.configure(default_level='info', filters='', formatter='pretty', thread_id=True)",
            "test_channel = alog.use_channel('test_merge_msg_json')",
            "test_channel.info({'log_code': '<TST00000000I>', 'message': 'This is a test'})",
        ])

        # run in subprocess and capture stderr
        _, stderr = subprocess.Popen(shlex.split(commands_to_run), stderr=subprocess.PIPE).communicate()
        logged_output = [line for line in stderr.split(b'\n') if len(line) > 0]

        # Parse the line header
        self.assertEqual(len(logged_output), 1)
        line = logged_output[0]
        parts = parse_pretty_line(line)
        self.assertIn('log_code', parts)
        self.assertEqual(parts['log_code'], '<TST00000000I>')
        self.assertIn('message', parts)
        self.assertEqual(parts['message'], 'This is a test')

    def test_log_code_arg(self):
        '''Test that logging with the first argument as a log code adds the code
        to the header correctly
        '''
        commands_to_run = get_subproc_cmds([
            "alog.configure(default_level='info', filters='', formatter='pretty', thread_id=True)",
            "test_channel = alog.use_channel('test_merge_msg_json')",
            "test_channel.info('<TST00000000I>', 'This is a test')",
        ])

        # run in subprocess and capture stderr
        _, stderr = subprocess.Popen(shlex.split(commands_to_run), stderr=subprocess.PIPE).communicate()
        logged_output = [line for line in stderr.split(b'\n') if len(line) > 0]

        # Parse the line header
        self.assertEqual(len(logged_output), 1)
        line = logged_output[0]
        parts = parse_pretty_line(line)
        self.assertIn('log_code', parts)
        self.assertEqual(parts['log_code'], '<TST00000000I>')
        self.assertIn('message', parts)
        self.assertEqual(parts['message'], 'This is a test')

    def test_log_code_with_formatting(self):
        '''Test that logging with a log code and formatting arguments to the
        message
        '''
        commands_to_run = get_subproc_cmds([
            "alog.configure(default_level='info', filters='', formatter='pretty', thread_id=True)",
            "test_channel = alog.use_channel('test_merge_msg_json')",
            "test_channel.info('<TST00000000I>', 'This is a test %d', 1)",
        ])

        # run in subprocess and capture stderr
        _, stderr = subprocess.Popen(shlex.split(commands_to_run), stderr=subprocess.PIPE).communicate()
        logged_output = [line for line in stderr.split(b'\n') if len(line) > 0]

        # Parse the line header
        self.assertEqual(len(logged_output), 1)
        line = logged_output[0]
        parts = parse_pretty_line(line)
        self.assertIn('log_code', parts)
        self.assertEqual(parts['log_code'], '<TST00000000I>')
        self.assertIn('message', parts)
        self.assertEqual(parts['message'], 'This is a test 1')

    def test_native_logging(self):
        '''Test that logging with the native logger works, despite overridden
        functions
        '''
        commands_to_run = get_subproc_cmds([
            "alog.configure(default_level='info', filters='', formatter='pretty', thread_id=True)",
            "import logging",
            "logging.info('This is a test %d', 1)",
        ])

        # run in subprocess and capture stderr
        _, stderr = subprocess.Popen(shlex.split(commands_to_run), stderr=subprocess.PIPE).communicate()
        logged_output = [line for line in stderr.split(b'\n') if len(line) > 0]

        # Parse the line header
        self.assertEqual(len(logged_output), 1)
        line = logged_output[0]
        parts = parse_pretty_line(line)
        self.assertNotIn('log_code', parts)
        self.assertIn('message', parts)
        self.assertEqual(parts['message'], 'This is a test 1')

    def test_log_code_json(self):
        '''Test that logging with a log code and the json formatter works as
        expected
        '''
        commands_to_run = get_subproc_cmds([
            "alog.configure(default_level='info', filters='', formatter='json', thread_id=True)",
            "test_channel = alog.use_channel('test_merge_msg_json')",
            "test_channel.info('<TST00000000I>', 'This is a test')",
        ])

        # run in subprocess and capture stderr
        _, stderr = subprocess.Popen(shlex.split(commands_to_run), stderr=subprocess.PIPE).communicate()
        logged_output = [line for line in stderr.split(b'\n') if len(line) > 0]

        # Parse the line header
        self.assertEqual(len(logged_output), 1)
        line = logged_output[0]
        parts = json.loads(line)
        self.assertIn('log_code', parts)
        self.assertEqual(parts['log_code'], '<TST00000000I>')
        self.assertIn('message', parts)
        self.assertEqual(parts['message'], 'This is a test')

if __name__ == "__main__":
    # has verbose output of tests; otherwise just says all passed or not
    unittest.main(verbosity=2)
