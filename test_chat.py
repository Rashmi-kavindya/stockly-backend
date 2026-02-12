#!/usr/bin/env python
"""Quick test of chat engine error handling"""

from chat_rules import ChatRulesEngine

def mock_db_error():
    """Simulate database connection failure"""
    raise Exception("Database connection failed - MySQL not running")

# Test with simulated DB error
engine = ChatRulesEngine(mock_db_error)

# Test various queries
test_queries = [
    "show sales for coca cola",
    "hi",
    "help",
    "show my goals"
]

for query in test_queries:
    print(f"\nQuery: {query}")
    response = engine.process_query(query, user_id=1)
    print(f"Response: {response}")
    print("-" * 60)
