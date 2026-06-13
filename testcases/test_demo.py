"""
隔离测试用例 — 验证 Allure @allure.feature / @allure.story 静态装饰器独立工作

目的:
  排除 test_transfer.py 中复杂参数化 (pytest_generate_tests) 带来的干扰，
  确认仅使用静态装饰器时 Allure Behaviors 页面是否正常。

运行方式:
    pytest testcases/test_demo.py -v --alluredir=reports/allure-results
"""

import allure


@allure.feature("调试专区")
@allure.story("调试故事")
def test_demo_static_labels():
    """
    极简测试：仅包含静态 @allure.feature 和 @allure.story 装饰器，
    不使用 allure.dynamic.*()、不使用参数化。
    """
    assert True