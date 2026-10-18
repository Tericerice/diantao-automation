import unittest

from utils import is_blacklisted


class BlacklistContractTest(unittest.TestCase):
    def test_yuanbao_mall_task_with_ocr_space_is_blacklisted(self):
        self.assertTrue(is_blacklisted("元宝 商城订单(0/1) +388"))

    def test_yuanbao_mall_task_with_zero_width_separator_is_blacklisted(self):
        self.assertTrue(is_blacklisted("元宝\u200b商城下单(0/1）+388"))


if __name__ == "__main__":
    unittest.main()
