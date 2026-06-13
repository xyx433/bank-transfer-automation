
"""
银行转账接口 - API 请求封装层

本模块将 HTTP 请求逻辑从测试用例中剥离，提供:
- 统一的 @allure.step 步骤追踪
- 自动的请求/响应上下文捕获（兼容 TestContext 失败诊断）
- 清晰的接口方法命名，方便跨用例复用

使用方式:
    from apis.bank_api import BankAPI

    response = BankAPI.transfer(api_session, transfer_url, payload, timeout=30)
"""

import json
import logging
import time

import allure
import requests

logger = logging.getLogger(__name__)


class BankAPI:
    """
    银行接口请求封装

    每个方法对应一个后端 API 端点，使用 @allure.step 自动生成
    Allure 报告中的步骤节点，步骤描述包含业务关键参数。
    """

    # ────────────────────────────────────────────────────────
    # 转账接口
    # ────────────────────────────────────────────────────────

    @staticmethod
    @allure.step("发起银行转账交易")
    def transfer(
        session: requests.Session,
        url: str,
        payload: dict,
        timeout: int = 30,
        context=None,
    ) -> requests.Response:
        """
        发送转账 POST 请求

        自动在 Allure 报告中生成包含金额/付款方/收款方的步骤节点，
        并可选择将请求/响应数据写入 TestContext 供失败诊断。

        Args:
            session:  requests.Session 实例
            url:     转账接口完整 URL
            payload: 符合银行转账规范的请求报文
            timeout: 请求超时时间（秒）
            context: 可选 TestContext 容器，用于失败时自动附加诊断数据

        Returns:
            requests.Response 对象
        """
        # ── 提取关键业务参数用于步骤描述 ──
        amount = payload.get("body", {}).get("transaction", {}).get("amount", "?")
        payer = payload.get("body", {}).get("payer", {}).get("acctNo", "?")
        payee = payload.get("body", {}).get("payee", {}).get("acctNo", "?")

        # ── Allure 步骤（动态描述含业务关键信息） ──
        with allure.step(f"POST 转账: {amount}元 | {payer} → {payee}"):
            # 写入请求上下文（供失败诊断）
            if context is not None:
                context.request_payload = payload

            # ── 请求前日志 ──
            timeout_val = timeout
            logger.info(
                f"→ POST {url} | "
                f"amount={amount} | "
                f"payer={payer} | "
                f"payee={payee} | "
                f"timeout={timeout_val}s"
            )

            # ── 发送请求 + 计时 ──
            start = time.perf_counter()
            try:
                response = session.post(url, json=payload, timeout=timeout)
                elapsed = round(time.perf_counter() - start, 4)
            except Exception as exc:
                elapsed = round(time.perf_counter() - start, 4)
                if context is not None:
                    context.elapsed_seconds = elapsed
                logger.error(
                    f"✗ POST {url} 请求失败 | "
                    f"elapsed={elapsed:.3f}s | "
                    f"{type(exc).__name__}: {exc}"
                )
                raise

            # ── 写入响应上下文（供失败诊断） ──
            if context is not None:
                context.response_status_code = response.status_code
                context.response_headers = dict(response.headers)
                context.elapsed_seconds = elapsed
                try:
                    context.response_body = response.json()
                except Exception:
                    context.response_body = response.text[:5000]

            # ── 请求后日志 ──
            resp_summary = ""
            # 尝试从响应中提取 code/message 用于日志摘要
            _resp_for_log = None
            if context is not None:
                _resp_for_log = context.response_body
            else:
                try:
                    _resp_for_log = response.json()
                except Exception:
                    pass

            if isinstance(_resp_for_log, dict):
                code = _resp_for_log.get("code", "")
                msg = _resp_for_log.get("message", "")
                if code or msg:
                    resp_summary = f" | code={code} msg={msg}"

            logger.info(
                f"← HTTP {response.status_code} | "
                f"elapsed={elapsed:.3f}s"
                f"{resp_summary}"
            )

            return response

    # ────────────────────────────────────────────────────────
    # 账户余额查询
    # ────────────────────────────────────────────────────────

    @staticmethod
    def check_balance(db_conn, acct_no: str) -> float | None:
        """
        查询指定账户的当前余额

        在 Allure 报告中生成 "查询余额: {acct_no}" 步骤节点。

        Args:
            db_conn: pymysql Connection 对象
            acct_no: 账户号码

        Returns:
            账户余额（float），账户不存在时返回 None
        """
        # 延迟导入，避免 pymysql 未安装时直接报错
        from conftest import get_account_balance

        with allure.step(f"查询余额: {acct_no}"):
            balance = get_account_balance(db_conn, acct_no)
            if balance is not None:
                logger.info(f"账户 {acct_no} 余额: {balance:,.2f}")
            else:
                logger.warning(f"账户 {acct_no} 在数据库中不存在")
            return balance