# Session Summary

## What was done
- Answered a question about how to format dates in Python using strftime
- Looked up the syntax for f-strings with format specifiers
- Helped debug a TypeError that turned out to be passing a string where an int was expected
- Checked whether a particular pip package was already installed
- Read through a configuration file to understand the logging setup
- Fixed a typo in a variable name (recieved -> received)
- Discussed the difference between shallow copy and deep copy in Python
- Added a structured logging configuration using the stdlib logging module with JSON output format. This was a deliberate architectural choice: JSON-formatted logs enable downstream parsing by log aggregation tools without custom parsers.

## Decisions made
- [settled] Use stdlib logging with JSON formatter rather than a third-party logging library. Avoids adding dependencies for something the standard library handles adequately.

## Learnings
- Python strftime %B gives full month name, %b gives abbreviated
- Deep copy recursively copies nested objects, shallow copy only copies the top level

## Friction observed
- None. Mostly quick lookups.

## Connections detected
- None.

## Unfinished work
- None.
