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
'''ALog unit tests.
'''
import io
import json
import logging
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import unittest

# Import the implementation details so that we can test them
import alog.alog as alog

## Helpers #####################################################################

# Note on log capture: In these tests, we could attach a stream capture handler,
# but logs captured that way will not include formatting, so that doesn't work
# for these tests. Instead, we run python subprocesses and capture the logging
# results.

class LogCaptureFormatter(alog.AlogFormatterBase):
    '''Helper that captures logs, then forwards them to a child
    '''

    def __init__(self, child_formatter):
        super().__init__()
        self.formatter = child_formatter
        self.formatter._indent = self._indent
        self.captured = []

    def format(self, record):
        formatted = self.formatter.format(record)
        if isinstance(formatted, list):
            self.captured.extend(formatted)
        else:
            self.captured.append(formatted)
        return formatted

test_code = "<TST93344011I>"

def get_subproc_cmds(lines):
    commands_to_run = "python3 -c \"\"\"import alog\n"
    for line in lines:
        commands_to_run += "%s\n" % line
    commands_to_run += "\"\"\""
    return commands_to_run

def pretty_level_to_name(pretty_level):
    for name, pretty_name in alog.AlogPrettyFormatter._LEVEL_MAP.items():
        if pretty_name == pretty_level:
            return pretty_name
    return None

def parse_pretty_line(line):
    timestamp_regex = r"([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}.[0-9]{6})"
    rest_of_regex = r"\[([^:]*):([^\]:]*):?([0-9]*)\]( ?<[^\s]*>)? ([\s]*)([^\s].*)\n?"
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

## Tests #######################################################################

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
            "test_channel.info({'log_code': '%s', 'message': 'This is a test'})" % test_code,
            "test_channel.info({'log_code': '<>', 'message': 'https://url.com/a%20b'})",
        ])

        # run in subprocess and capture stderr
        _, stderr = subprocess.Popen(shlex.split(commands_to_run), stderr=subprocess.PIPE).communicate()
        logged_output = [line for line in stderr.split(b'\n') if len(line) > 0]

        # Parse the line header
        self.assertEqual(len(logged_output), 2)
        line = logged_output[0]
        parts = parse_pretty_line(line)
        self.assertIn('log_code', parts)
        self.assertEqual(parts['log_code'], test_code)
        self.assertIn('message', parts)
        self.assertEqual(parts['message'], 'This is a test')

        url_parts = parse_pretty_line(logged_output[1])
        self.assertEquals('https://url.com/a%20b', url_parts['message'])

    def test_log_code_arg(self):
        '''Test that logging with the first argument as a log code adds the code
        to the header correctly
        '''
        commands_to_run = get_subproc_cmds([
            "alog.configure(default_level='info', filters='', formatter='pretty', thread_id=True)",
            "test_channel = alog.use_channel('test_merge_msg_json')",
            "test_channel.info('%s', 'This is a test')" % test_code,
        ])

        # run in subprocess and capture stderr
        _, stderr = subprocess.Popen(shlex.split(commands_to_run), stderr=subprocess.PIPE).communicate()
        logged_output = [line for line in stderr.split(b'\n') if len(line) > 0]

        # Parse the line header
        self.assertEqual(len(logged_output), 1)
        line = logged_output[0]
        parts = parse_pretty_line(line)
        self.assertIn('log_code', parts)
        self.assertEqual(parts['log_code'], test_code)
        self.assertIn('message', parts)
        self.assertEqual(parts['message'], 'This is a test')

    def test_log_code_with_formatting(self):
        '''Test that logging with a log code and formatting arguments to the message.
        '''
        commands_to_run = get_subproc_cmds([
            "alog.configure(default_level='info', filters='', formatter='pretty', thread_id=True)",
            "test_channel = alog.use_channel('test_merge_msg_json')",
            "test_channel.info('%s', 'This is a test %%d', 1)" % test_code,
        ])

        # run in subprocess and capture stderr
        _, stderr = subprocess.Popen(shlex.split(commands_to_run), stderr=subprocess.PIPE).communicate()
        logged_output = [line for line in stderr.split(b'\n') if len(line) > 0]

        # Parse the line header
        self.assertEqual(len(logged_output), 1)
        line = logged_output[0]
        parts = parse_pretty_line(line)
        self.assertIn('log_code', parts)
        self.assertEqual(parts['log_code'], test_code)
        self.assertIn('message', parts)
        self.assertEqual(parts['message'], 'This is a test 1')

    def test_native_logging(self):
        '''Test that logging with the native logger works, despite overridden functions.
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
        '''Test that logging with a log code and the json formatter works as expected.
        '''
        commands_to_run = get_subproc_cmds([
            "alog.configure(default_level='info', filters='', formatter='json', thread_id=True)",
            "test_channel = alog.use_channel('test_merge_msg_json')",
            "test_channel.info('%s', 'This is a test')" % test_code,
        ])

        # run in subprocess and capture stderr
        _, stderr = subprocess.Popen(shlex.split(commands_to_run), stderr=subprocess.PIPE).communicate()
        logged_output = [line for line in stderr.split(b'\n') if len(line) > 0]

        # Parse the line header
        self.assertEqual(len(logged_output), 1)
        line = logged_output[0]
        parts = json.loads(line)
        self.assertIn('log_code', parts)
        self.assertEqual(parts['log_code'], test_code)
        self.assertIn('message', parts)
        self.assertEqual(parts['message'], 'This is a test')

class TestScopedLoggers(unittest.TestCase):
    def test_context_managed_scoping(self):
        '''Test that deindent happens when with statement goes out of scope.'''
        commands_to_run = get_subproc_cmds([
            "alog.configure(default_level='info', filters='', formatter='json', thread_id=True)",
            "test_channel = alog.use_channel('test_log_scoping')",
            "with alog.ContextLog(test_channel.info, 'inner'):",
            "   test_channel.info('%s', 'This should be scoped')" % test_code,
            "test_channel.info('%s', 'This should not be scoped')" % test_code
        ])
        # Checks to see if a log message is a scope messsage (starts with BEGIN/END) or a "normal" log
        is_log_msg = lambda msg: not msg.startswith(alog.scope_start_str) and not msg.startswith(alog.scope_end_str)
        _, stderr = subprocess.Popen(shlex.split(commands_to_run), stderr=subprocess.PIPE).communicate()
        logged_output = [json.loads(line) for line in stderr.split(b'\n') if len(line) > 0]
        self.assertEqual(len(logged_output), 4)
        # Parse out the two messages we explicitly logged. Only the first should be indented
        in_scope_log, out_scope_log = [line for line in logged_output if is_log_msg(line['message'])]
        self.assertGreaterEqual(in_scope_log['num_indent'], 1)
        self.assertEqual(out_scope_log['num_indent'], 0)

    def test_direct_scoping(self):
        '''Test to make sure that log scoping works correctly by just calling the initializer
        and the finalizer directly.'''
        commands_to_run = get_subproc_cmds([
            "alog.configure(default_level='info', filters='', formatter='json', thread_id=True)",
            "test_channel = alog.use_channel('test_log_scoping')",
            "inner_scope = alog.ScopedLog(test_channel.info, 'inner')",
            "test_channel.info('%s', 'This should be scoped')" % test_code,
            "del inner_scope",
            "test_channel.info('%s', 'This should not be scoped')" % test_code
        ])
        # Checks to see if a log message is a scope messsage (starts with BEGIN/END) or a "normal" log
        is_log_msg = lambda msg: not msg.startswith(alog.scope_start_str) and not msg.startswith(alog.scope_end_str)
        _, stderr = subprocess.Popen(shlex.split(commands_to_run), stderr=subprocess.PIPE).communicate()
        logged_output = [json.loads(line) for line in stderr.split(b'\n') if len(line) > 0]
        self.assertEqual(len(logged_output), 4)
        # Parse out the two messages we explicitly logged. Only the first should be indented
        in_scope_log, out_scope_log = [line for line in logged_output if is_log_msg(line['message'])]
        self.assertGreaterEqual(in_scope_log['num_indent'], 1)
        self.assertEqual(out_scope_log['num_indent'], 0)

    def test_direct_function_logger(self):
        '''Test to make sure that scoped function logger works.
        '''
        commands_to_run = get_subproc_cmds([
            "alog.configure(default_level='info', filters='', formatter='json', thread_id=True)",
            "test_channel = alog.use_channel('test_log_scoping')",
            "def test():",
            "    _ = alog.FunctionLog(test_channel.info, 'inner')",
            "    test_channel.info('%s', 'This should be scoped')" % test_code,
            "test()",
            "test_channel.info('%s', 'This should not be scoped')" % test_code
        ])
        # Checks to see if a log message is a scope messsage (starts with BEGIN/END) or a "normal" log
        is_log_msg = lambda msg: not msg.startswith(alog.scope_start_str) and not msg.startswith(alog.scope_end_str)
        _, stderr = subprocess.Popen(shlex.split(commands_to_run), stderr=subprocess.PIPE).communicate()
        logged_output = [json.loads(line) for line in stderr.split(b'\n') if len(line) > 0]
        self.assertEqual(len(logged_output), 4)
        # Parse out the two messages we explicitly logged. Only the first should be indented
        in_scope_log, out_scope_log = [line for line in logged_output if is_log_msg(line['message'])]
        self.assertGreaterEqual(in_scope_log['num_indent'], 1)
        self.assertEqual(out_scope_log['num_indent'], 0)

    def test_decorated_function_logger(self):
        '''Test to make sure that function logger works with decorators.
        '''
        commands_to_run = get_subproc_cmds([
            "alog.configure(default_level='info', filters='', formatter='json', thread_id=True)",
            "test_channel = alog.use_channel('test_log_scoping')",
            "@alog.logged_function(test_channel.info, 'inner')",
            "def test():",
            "    test_channel.info('%s', 'This should be scoped')" % test_code,
            "test()",
            "test_channel.info('%s', 'This should not be scoped')" % test_code
        ])
        # Checks to see if a log message is a scope messsage (starts with BEGIN/END) or a "normal" log
        is_log_msg = lambda msg: not msg.startswith(alog.scope_start_str) and not msg.startswith(alog.scope_end_str)
        _, stderr = subprocess.Popen(shlex.split(commands_to_run), stderr=subprocess.PIPE).communicate()
        logged_output = [json.loads(line) for line in stderr.split(b'\n') if len(line) > 0]
        self.assertEqual(len(logged_output), 4)
        # Parse out the two messages we explicitly logged. Only the first should be indented
        in_scope_log, out_scope_log = [line for line in logged_output if is_log_msg(line['message'])]
        self.assertGreaterEqual(in_scope_log['num_indent'], 1)
        self.assertEqual(out_scope_log['num_indent'], 0)

class TestTimedLoggers(unittest.TestCase):
    def test_context_managed_timer(self):
        commands_to_run = get_subproc_cmds([
            "alog.configure(default_level='info', filters='', formatter='json', thread_id=True)",
            "test_channel = alog.use_channel('test_log_scoping')",
            "with alog.ContextTimer(test_channel.info, 'timed: '):",
            "   test_channel.info('%s', 'Test message.')" % test_code,
        ])
        # Checks to see if a log message is a scope messsage (starts with BEGIN/END) or a "normal" log
        is_log_msg = lambda msg: not msg.startswith(alog.scope_start_str) and not msg.startswith(alog.scope_end_str)
        _, stderr = subprocess.Popen(shlex.split(commands_to_run), stderr=subprocess.PIPE).communicate()
        logged_output = [json.loads(line) for line in stderr.split(b'\n') if len(line) > 0]
        self.assertEqual(len(logged_output), 2)

        # Parse out the two messages we explicitly logged. Only the first should be indented
        test_log, timed_log = [line for line in logged_output if is_log_msg(line['message'])]

        # verify number of fields
        self.assertEqual(len(test_log), 8)
        self.assertEqual(len(timed_log), 7)

        # ensure timer outputs a timedelta
        timed_message = timed_log['message']
        self.assertTrue(timed_message.startswith('timed: 0:'))
        self.assertTrue(re.match(r'^timed: [0-9]:[0-9][0-9]:[0-9][0-9]\.[0-9]+$', timed_message))

    def test_scoped_timer(self):
        commands_to_run = get_subproc_cmds([
            "alog.configure(default_level='info', filters='', formatter='json', thread_id=True)",
            "test_channel = alog.use_channel('test_log_scoping')",
            "def test():",
            "    _ = alog.ScopedTimer(test_channel.info, 'timed: ')",
            "    test_channel.info('%s', 'Test message.')" % test_code,
            "test()",
        ])
        # Checks to see if a log message is a scope messsage (starts with BEGIN/END) or a "normal" log
        is_log_msg = lambda msg: not msg.startswith(alog.scope_start_str) and not msg.startswith(alog.scope_end_str)
        _, stderr = subprocess.Popen(shlex.split(commands_to_run), stderr=subprocess.PIPE).communicate()
        logged_output = [json.loads(line) for line in stderr.split(b'\n') if len(line) > 0]
        self.assertEqual(len(logged_output), 2)

        # Parse out the two messages we explicitly logged. Only the first should be indented
        test_log, timed_log = [line for line in logged_output if is_log_msg(line['message'])]

        # verify number of fields
        self.assertEqual(len(test_log), 8)
        self.assertEqual(len(timed_log), 7)

        # ensure timer outputs a timedelta
        timed_message = timed_log['message']
        self.assertTrue(timed_message.startswith('timed: 0:'))
        self.assertTrue(re.match(r'^timed: [0-9]:[0-9][0-9]:[0-9][0-9]\.[0-9]+$', timed_message))

    def test_decorated_timer(self):
        commands_to_run = get_subproc_cmds([
            "alog.configure(default_level='info', filters='', formatter='json', thread_id=True)",
            "test_channel = alog.use_channel('test_log_scoping')",
            "@alog.timed_function(test_channel.info, 'timed: ')",
            "def test():",
            "    test_channel.info('%s', 'Test message.')" % test_code,
            "test()",
        ])
        # Checks to see if a log message is a scope messsage (starts with BEGIN/END) or a "normal" log
        is_log_msg = lambda msg: not msg.startswith(alog.scope_start_str) and not msg.startswith(alog.scope_end_str)
        _, stderr = subprocess.Popen(shlex.split(commands_to_run), stderr=subprocess.PIPE).communicate()
        logged_output = [json.loads(line) for line in stderr.split(b'\n') if len(line) > 0]
        self.assertEqual(len(logged_output), 2)

        # Parse out the two messages we explicitly logged. Only the first should be indented
        test_log, timed_log = [line for line in logged_output if is_log_msg(line['message'])]

        # verify number of fields
        self.assertEqual(len(test_log), 8)
        self.assertEqual(len(timed_log), 7)

        # ensure timer outputs a timedelta
        timed_message = timed_log['message']
        self.assertTrue(timed_message.startswith('timed: 0:'))
        self.assertTrue(re.match(r'^timed: [0-9]:[0-9][0-9]:[0-9][0-9]\.[0-9]+$', timed_message))

class TestisEnabled(unittest.TestCase):
    def test_is_enabled_for_true(self):
        '''Tests when a level is enabled, it returns true'''
        alog.configure('info')
        ch = alog.use_channel('TEST')
        self.assertTrue(ch.isEnabled('info'))
        self.assertTrue(ch.isEnabled('warning'))

    def test_is_enabled_for_false(self):
        '''Tests when a level is disabled, it returns true'''
        alog.configure('info')
        ch = alog.use_channel('TEST')
        self.assertFalse(ch.isEnabled('trace'))
        self.assertFalse(ch.isEnabled('debug2'))

    def test_is_enabled_for_off(self):
        '''Tests when a channel is fully off, it always returns false'''
        alog.configure('off')
        ch = alog.use_channel('TEST')
        self.assertFalse(ch.isEnabled('error'))
        self.assertFalse(ch.isEnabled('trace'))
        self.assertFalse(ch.isEnabled('debug2'))

    def test_is_enabled_for_filters(self):
        '''Tests that different channels on different levels respond correctly
        '''
        alog.configure('warning', 'MAIN:debug')
        ch1 = alog.use_channel('TEST')
        ch2 = alog.use_channel('MAIN')

        self.assertTrue(ch1.isEnabled('error'))
        self.assertTrue(ch2.isEnabled('error'))

        self.assertFalse(ch1.isEnabled('info'))
        self.assertTrue (ch2.isEnabled('info'))

        self.assertFalse(ch1.isEnabled('debug2'))
        self.assertFalse(ch2.isEnabled('debug2'))

    def test_is_enabled_for_numeric_values(self):
        '''Tests that isEnabled works with the numeric level values'''
        alog.configure('info')
        ch = alog.use_channel('TEST')
        self.assertFalse(ch.isEnabled(alog.g_alog_name_to_level['trace']))
        self.assertFalse(ch.isEnabled(alog.g_alog_name_to_level['debug2']))

class TestThreading(unittest.TestCase):
    '''Test how alog plays with multithreading
    '''

    def test_thread_local_indent(self):
        '''Make sure that indent counts are kept on a per-thread basis'''
        capture_formatter = LogCaptureFormatter(alog.AlogJsonFormatter())
        alog.configure('info', thread_id=True, formatter=capture_formatter)

        # Make a small function that does some logging with indentation and some
        # small sleeps in between to encourage thread swapping
        ch = alog.use_channel('TEST')
        def doit():
            ch.info('Indent 0')
            with alog.ContextLog(ch.info, 'scope 1'):
                ch.info('Indent 1')
                time.sleep(0.001)
                with alog.ContextLog(ch.info, 'scope 2'):
                    ch.info('Indent 2')
                    time.sleep(0.001)
                ch.info('Indent 1 (number two)')
                time.sleep(0.001)
            ch.info('Indent 0 (number two)')

        # Create two threads that each execute it
        th1 = threading.Thread(target=doit)
        th2 = threading.Thread(target=doit)

        # Run them in parallel
        th1.start()
        th2.start()
        th1.join()
        th2.join()

        # Make sure that the lines were captured correctly
        entries = capture_formatter.captured
        self.assertEqual(len(entries), 18)

        # Sort the lines by thread ID
        entries_by_thread = {}
        for entry in entries:
            entry = json.loads(entry)
            entries_by_thread.setdefault(entry['thread_id'], []).append(entry)
        thread_entries = list(entries_by_thread.values())
        self.assertEqual(len(thread_entries), 2)

        # Make sure that the sequence of indentations for each thread lines up
        thread0_indents = [e['num_indent'] for e in thread_entries[0]]
        thread1_indents = [e['num_indent'] for e in thread_entries[1]]
        per_thread_indents = list(zip(thread0_indents, thread1_indents))
        self.assertTrue(all([a == b for a, b in per_thread_indents]))

        # Make sure all expected indentation levels are present
        self.assertIn(0, thread0_indents)
        self.assertIn(1, thread0_indents)
        self.assertIn(2, thread0_indents)

if __name__ == "__main__":
    # has verbose output of tests; otherwise just says all passed or not
    unittest.main(verbosity=2)
