import unittest
import asyncio

from provider import request_llama_cpp

class TestLlamaCPP(unittest.TestCase):
    def test_request_llama_cpp(self):
        result = asyncio.run(request_llama_cpp("Always answer 'PC_OK' to user", "Test string"))
        self.assertEqual(result.get("message"), "PC_OK")

if __name__ == "__main__":
    unittest.main()