import unittest
from datetime import datetime

from src.log_analysis.log_parser import LogParser, LogLevel, LogFormat


class TestLogParser(unittest.TestCase):
    def setUp(self):
        self.parser = LogParser()

    def test_syslog_uses_current_year(self):
        line = "Jan 15 14:30:45 server1 sshd: Failed password for root"
        entry = self.parser.parse_line(line, 1)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.timestamp.year, datetime.now().year)
        self.assertEqual(entry.level, LogLevel.ERROR)

    def test_json_fatal_level(self):
        line = '{"timestamp": "2024-01-15T14:30:45Z", "level": "FATAL", "message": "Kernel panic"}'
        entry = self.parser.parse_line(line, 1, LogFormat.JSON)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.level, LogLevel.FATAL)


if __name__ == "__main__":
    unittest.main()
