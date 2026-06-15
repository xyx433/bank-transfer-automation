"""
银行转账接口 - 参数化自动化测试

基于 data/transfer_data.yaml 数据驱动，覆盖正常流程与常见异常场景。

运行方式:
    # 运行全部转账用例
    pytest testcases/test_transfer.py -v

    # 仅运行冒烟测试
    pytest testcases/test_transfer.py -v -m smoke

    # 仅运行反向用例
    pytest testcases/test_transfer.py -v -m negative

    # 运行并生成 Allure 报告
    pytest testcases/test_transfer.py -v --alluredir=reports/allure-results
"""

import json
import logging
import time

import allure
import pytest

from apis.bank_api import BankAPI
from conftest import (
    build_request_payload,
    get_account_balance,
    generate_nonce,
    generate_timestamp,
    generate_tran_seq_no,
    generate_idempotency_key,
    ERROR_CODES,
    TestContext,
)



# ============================================================
# 日志
# ============================================================
logger = logging.getLogger(__name__)

# ============================================================
# 注意：
#   YAML 数据的加载和参数化注入已由 conftest.py 中的
#   pytest_generate_tests() 钩子自动完成。
#   测试文件无需再手写 @pytest.mark.parametrize 或 YAML 路径。
#
#   约定：
#     test_transfer.py → 自动加载 data/transfer*.yaml
#     新增 YAML 文件或新增用例条目 → 自动执行，代码零改动
# ============================================================
# 响应结构防御性校验（公共工具）
# ============================================================

def _assert_response_structure(
    resp_json: dict,
    expected_keys: list[str],
    context: str = "",
) -> None:
    """
    校验 HTTP 响应 JSON 是否包含预期的业务字段（具备"拆壳"能力）

    后端返回的标准结构为带壳 JSON：
        {"code": "...", "message": "...", "data": {"header": {...}, "body": {...}}}

    本函数会自动识别该结构：
      - 如果 resp_json 包含 "code" 和 "data"，则进入 resp_json["data"] 内部检查
        expected_keys（如 header / body），缺少时报错信息指向 data 内部；
      - 否则在顶层直接检查 expected_keys。

    在访问 header / body 等字段之前调用，避免因后端返回异常结构导致 KeyError。

    Args:
        resp_json:     response.json() 返回的字典
        expected_keys: 必须在业务数据中存在的 key 列表，如 ["header", "body"]
        context:       调用上下文描述（用于错误信息）

    Raises:
        AssertionError: 缺少预期字段时，打印实际 JSON 结构与修复提示
    """
    # ── 拆壳：标准 {code, message, data} 结构 → 进入 data 内部检查 ──
    if "code" in resp_json and "data" in resp_json:
        inner = resp_json["data"]
        if not isinstance(inner, dict):
            raise AssertionError(
                f"{context}: resp_json['data'] 不是字典类型, "
                f"实际类型: {type(inner).__name__}\n"
                f"data 内容: {json.dumps(inner, ensure_ascii=False)[:500]}"
            )
        missing = [k for k in expected_keys if k not in inner]
        if missing:
            actual_keys = list(inner.keys())
            snippet = json.dumps(inner, ensure_ascii=False)[:800]
            raise AssertionError(
                f"{context}: 响应JSON的 data 内部缺少字段 {missing}\n"
                f"实际 data 字段: {actual_keys}\n"
                f"完整 data 内容: {snippet}\n"
                f"提示: 请检查后端返回的 data 业务数据结构"
            )
    else:
        # ── 非标准结构 → 直接在顶层检查 ──
        missing = [k for k in expected_keys if k not in resp_json]
        if missing:
            actual_keys = list(resp_json.keys())
            snippet = json.dumps(resp_json, ensure_ascii=False)[:800]
            raise AssertionError(
                f"{context}: 响应JSON顶层缺少字段 {missing}\n"
                f"实际顶层字段: {actual_keys}\n"
                f"完整响应内容: {snippet}"
            )

# ============================================================
# 数据库余额校验函数
# ============================================================

def verify_account_balance(
    db_conn,
    acct_no: str,
    initial_balance: float,
    amount: float,
    fee: float,
    tc_id: str = "",
    expected_balance_change: float | None = None,
) -> None:
    """
    验证转账后付款方账户余额是否正确扣减

    核心公式：期望余额 = 初始余额 − 转账金额 − 手续费

    内置重试机制：由于 Java 后端可能异步处理转账（余额更新有微小延迟），
    本函数最多重试 5 次（每次间隔 0.3s），以等待后端提交余额变更。

    执行步骤：
      1. 查询数据库获取当前余额（带重试）
      2. 计算期望余额：initial_balance − amount − fee
      3. 断言 实际余额 == 期望余额

    Args:
        db_conn:         pymysql Connection 对象
        acct_no:         付款账号
        initial_balance: 转账前余额
        amount:          转账金额
        fee:             实际手续费（从响应 body.feeAmount 获取）
        tc_id:           用例 ID（用于日志/错误信息）

    Raises:
        AssertionError:   余额不匹配或账户不存在
        pymysql.MySQLError: 数据库查询异常
    """
    # 使用自定义余额变动量（如本人同名卡互转场景），否则默认 = -(amount + fee)
    if expected_balance_change is not None:
        expected_balance = round(initial_balance + expected_balance_change, 2)
    else:
        expected_balance = round(initial_balance - amount - fee, 2)
    max_retries = 5
    retry_delay = 0.3  # 秒

    last_balance = None
    for attempt in range(1, max_retries + 1):
        # ---- 查询当前余额 ----
        current_balance = get_account_balance(db_conn, acct_no)

        # ---- 账户存在性校验 ----
        if current_balance is None:
            raise AssertionError(
                f"[{tc_id}] 余额校验失败: 账户 {acct_no} 在数据库中不存在，"
                f"无法验证余额变动"
            )

        current_balance = round(current_balance, 2)
        last_balance = current_balance

        if current_balance == expected_balance:
            logger.info(
                f"[{tc_id}] 余额校验通过: acct={acct_no}, "
                f"{initial_balance:,.2f} → {current_balance:,.2f} "
                f"(amount={amount:,.2f}, fee={fee:,.2f})"
                f"{f' (第{attempt}次查询)' if attempt > 1 else ''}"
            )
            return

        if attempt < max_retries:
            logger.debug(
                f"[{tc_id}] 余额尚未更新 (尝试 {attempt}/{max_retries}), "
                f"期望 {expected_balance:,.2f}, 实际 {current_balance:,.2f}, "
                f"等待 {retry_delay}s 后重试..."
            )
            time.sleep(retry_delay)

    # ---- 所有重试耗尽，断言失败 ----
    assert last_balance == expected_balance, (
        f"[{tc_id}] 账户余额校验失败! (已重试 {max_retries} 次)\n"
        f"  付款账号: {acct_no}\n"
        f"  初始余额: {initial_balance:,.2f}\n"
        f"  转账金额: {amount:,.2f}\n"
        f"  扣手续费: {fee:,.2f}\n"
        f"  期望余额: {expected_balance:,.2f}\n"
        f"  实际余额: {last_balance:,.2f}\n"
        f"  差额:     {last_balance - expected_balance:,.2f}"
    )


# ============================================================
# 测试用例
# ============================================================

@allure.feature("转账业务")
@allure.story("转账交易")
def test_transfer(api_session, transfer_url, db_conn, test_context, tc: dict):
    """
    银行转账接口参数化测试

    每条 YAML 数据驱动一条用例:
    1. 根据 tc['overrides'] 构建请求报文
    2. (正向用例) 查询付款方转账前余额
    3. 发送 POST 请求到转账接口
    4. 断言 HTTP 状态码、respCode、tranStatus 与预期一致
    5. (正向用例 + DB可用) 校验余额 = 初始余额 − amount − fee
    """
    tc_id = tc["id"]
    tc_name = tc["name"]
    description = tc.get("description", "")
    expected = tc["expected"]
    overrides = tc.get("overrides", {})

    # ---- 提前提取预期 respCode（必须在 Allure 动态标题之前完成） ----
    # 原因：后续 allure.dynamic.title / story / severity 均依赖此变量，
    #       必须在首次使用前完成赋值，避免 Python UnboundLocalError。
    expected_resp_code = expected.get("respCode", "")

    # ---- 提取金额用于动态标题和附件描述 ----
    transfer_amount = overrides.get("body", {}).get("transaction", {}).get("amount")
    if transfer_amount is None:
        from conftest import get_default_request_body
        transfer_amount = get_default_request_body()["body"]["transaction"]["amount"]

    # ---- Allure 报告标注（企业级分类） ----
    # 动态标题：正向用例含金额，异常用例含预期错误码
    if expected_resp_code == "000000":
        allure.dynamic.title(f"{tc_id}: {tc_name} [转账 {transfer_amount}元]")
    else:
        allure.dynamic.title(f"{tc_id}: {tc_name} [预期 {expected_resp_code}]")
    allure.dynamic.description(description)
    for tag in tc.get("tags", []):
        allure.dynamic.tag(tag)

    # 动态设置 story（在静态 @allure.feature("转账业务") 基础上细化故事分类）
    # 注意: 不再调用 allure.dynamic.feature()，避免与静态装饰器重复
    if expected_resp_code == "000000":
        allure.dynamic.story("正向流程")
    else:
        allure.dynamic.story("异常流程")

    # severity 仍在此处按用例类型动态设置
    if expected_resp_code == "000000":
        allure.dynamic.severity(allure.severity_level.CRITICAL)
    else:
        allure.dynamic.severity(allure.severity_level.NORMAL)

    # ---- 1. 构建请求报文 ----
    logger.info(f"[{tc_id}] 开始执行: {tc_name}")
    payload = build_request_payload(overrides)
    logger.debug(f"[{tc_id}] 请求体:\n{payload}")

    is_positive_case = (expected_resp_code == "000000")
    payer_acct = payload["body"]["payer"]["acctNo"]
    initial_balance = None

    # ---- 2. 正向用例：查询转账前余额 ----
    if is_positive_case and db_conn is not None:
        with allure.step(f"查询付款方转账前余额: {payer_acct}"):
            try:
                initial_balance = get_account_balance(db_conn, payer_acct)
                if initial_balance is not None:
                    logger.info(
                        f"[{tc_id}] 转账前余额: {payer_acct} = {initial_balance:,.2f}"
                    )
                    test_context.add_db_snapshot(
                        "转账前", payer_acct, initial_balance
                    )
                else:
                    logger.warning(
                        f"[{tc_id}] 账户 {payer_acct} 不存在，跳过余额校验"
                    )
            except Exception as e:
                logger.warning(
                    f"[{tc_id}] 查询初始余额失败，跳过余额校验: {type(e).__name__}: {e}"
                )
                initial_balance = None

    # ---- 3. 发送请求（自动捕获上下文到 test_context） ----
    with allure.step("发送转账请求"):
        logger.info(
            f"[{tc_id}] POST {transfer_url} "
            f"金额={payload['body']['transaction']['amount']} "
            f"付款方={payer_acct} "
            f"收款方={payload['body']['payee']['acctNo']}"
        )
        response = BankAPI.transfer(
            api_session,
            transfer_url,
            payload,
            timeout=30,
            context=test_context,
        )

    # ---- 附加请求体与响应体到 Allure 报告（所有用例均可见） ----
    allure.attach(
        json.dumps(payload, indent=2, ensure_ascii=False),
        name="📤 Request Body (请求体)",
        attachment_type=allure.attachment_type.JSON,
    )
    resp_json = response.json()
    allure.attach(
        json.dumps(resp_json, indent=2, ensure_ascii=False),
        name="📥 Response Body (响应体)",
        attachment_type=allure.attachment_type.JSON,
    )

    # ---- 4. 基础断言 ----
    expected_http = expected.get("http_status", 200)

    with allure.step(f"验证 HTTP 状态码 = {expected_http}"):
        assert response.status_code == expected_http, (
            f"[{tc_id}] HTTP状态码不匹配: "
            f"期望 {expected_http}, 实际 {response.status_code}, "
            f"响应体: {response.text[:500]}"
        )

    logger.debug(f"[{tc_id}] 响应体:\n{resp_json}")

    # ---- 非200响应专项处理：校验 code 字段并提前返回 ----
    # 部分负向用例（如参数校验）在框架层即返回 4xx，响应结构不含
    # 标准 {code, data: {header, body}} 包装，直接以 {code, message} 形式返回。
    expected_code = expected.get("expectedCode")
    if expected_http != 200 and expected_code is not None:
        with allure.step(f"验证 code = {expected_code}"):
            actual_code = resp_json.get("code", "")
            assert actual_code == expected_code, (
                f"[{tc_id}] code不匹配: "
                f"期望 {expected_code}, 实际 {actual_code}, "
                f"message: {resp_json.get('message', 'N/A')}"
            )
        logger.info(f"[{tc_id}] ✓ 通过")
        return  # 非200响应不做后续 header/body 结构校验

    # ---- 防御：校验响应 JSON 结构（自动拆壳到 data 内部检查 header/body） ----
    _assert_response_structure(
        resp_json,
        ["header", "body"],
        context=f"[{tc_id}] 响应结构校验",
    )

    # 拆壳：提取业务数据层（标准 {code, data} 包装 → 取 data；否则用原 JSON）
    data = resp_json.get("data", resp_json)

    with allure.step(f"验证 respCode = {expected_resp_code}"):
        actual_resp_code = data["header"]["respCode"]
        assert actual_resp_code == expected_resp_code, (
            f"[{tc_id}] respCode不匹配: "
            f"期望 {expected_resp_code}, 实际 {actual_resp_code}, "
            f"respMsg: {data['header'].get('respMsg', 'N/A')}"
        )

    expected_tran_status = expected["tranStatus"]
    with allure.step(f"验证 tranStatus = {expected_tran_status}"):
        actual_tran_status = data["body"]["tranStatus"]
        assert actual_tran_status == expected_tran_status, (
            f"[{tc_id}] tranStatus不匹配: "
            f"期望 {expected_tran_status}, 实际 {actual_tran_status}"
        )

    # ---- 5. 成功响应额外校验 ----
    if expected_resp_code == "000000":
        with allure.step("验证成功响应体完整性"):
            body = data["body"]
            # 返回受理流水号
            assert body.get("acpTranSeqNo"), (
                f"[{tc_id}] 成功响应缺少 acpTranSeqNo"
            )
            # 收款账号脱敏
            assert "****" in body.get("payeeAcctMask", ""), (
                f"[{tc_id}] 收款账号未脱敏: {body.get('payeeAcctMask')}"
            )
            # 实际金额与请求一致
            assert body.get("actualAmount") == payload["body"]["transaction"]["amount"], (
                f"[{tc_id}] 实际到账金额不匹配: "
                f"期望 {payload['body']['transaction']['amount']}, "
                f"实际 {body.get('actualAmount')}"
            )
            # 手续费 ≥ 0
            assert body.get("feeAmount", -1) >= 0, (
                f"[{tc_id}] 手续费异常: {body.get('feeAmount')}"
            )
            # 返回了核心流水号
            assert body.get("coreSerialNo"), (
                f"[{tc_id}] 成功响应缺少 coreSerialNo"
            )
            # 返回了人行清算流水号
            assert body.get("hostSeqNo"), (
                f"[{tc_id}] 成功响应缺少 hostSeqNo"
            )

            # ---- 可选：精确断言手续费金额 ----
            expected_fee = expected.get("expectedFeeAmount")
            if expected_fee is not None:
                actual_fee = body.get("feeAmount")
                assert actual_fee == expected_fee, (
                    f"[{tc_id}] 手续费金额不匹配: "
                    f"期望 {expected_fee}, 实际 {actual_fee}"
                )

        # ---- 6. 数据库余额校验（正向用例 + DB 可用） ----
        if db_conn is not None and initial_balance is not None:
            # 【关键新增】读取 YAML 中的 skip_balance_check 指令
            # 如果 YAML 里写了 skip_balance_check: true，就跳过后面的余额计算
            skip_check = expected.get("skip_balance_check", False)
            if skip_check:
                logger.info(f"[{tc_id}] 跳过余额校验: YAML 配置 skip_balance_check=True")
            else:
                # 只有不跳过的时候，才执行下面的余额校验逻辑
                balance_change = expected.get("expectedBalanceChange")
                with allure.step(
                    f"验证余额: {initial_balance:,.2f} "
                    f"− {payload['body']['transaction']['amount']:,.2f} "
                    f"− {data['body'].get('feeAmount', 0):,.2f}"
                ):
                    try:
                        verify_account_balance(
                            db_conn=db_conn,
                            acct_no=payer_acct,
                            initial_balance=initial_balance,
                            amount=payload["body"]["transaction"]["amount"],
                            fee=data["body"].get("feeAmount", 0),
                            tc_id=tc_id,
                            expected_balance_change=balance_change,
                        )
                        # 余额校验通过后，记录转账后余额快照
                        try:
                            final_balance = get_account_balance(db_conn, payer_acct)
                            test_context.add_db_snapshot(
                                "转账后(校验通过)", payer_acct, final_balance
                            )
                        except Exception:
                            pass
                    except AssertionError:
                        # 余额断言失败 → 捕获当前余额快照后再抛出
                        try:
                            actual_balance = get_account_balance(db_conn, payer_acct)
                            test_context.add_db_snapshot(
                                "转账后(校验失败)", payer_acct, actual_balance
                            )
                        except Exception:
                            pass
                        raise
                    except Exception as e:
                        # 数据库连接异常等非断言错误 → 记录但不中断
                        logger.error(
                            f"[{tc_id}] 余额校验执行异常: {type(e).__name__}: {e}"
                        )
    # ---- 7. 失败响应额外校验 ----
    else:
        with allure.step("验证失败响应体完整性"):
            body = data["body"]
            # tranStatus 必须为 FAILED
            assert body["tranStatus"] == "FAILED", (
                f"[{tc_id}] 失败响应 tranStatus 应为 FAILED, "
                f"实际: {body['tranStatus']}"
            )
            # 应包含失败原因
            assert body.get("failReasonCode"), (
                f"[{tc_id}] 失败响应缺少 failReasonCode"
            )
            assert body.get("failReasonDesc"), (
                f"[{tc_id}] 失败响应缺少 failReasonDesc"
            )

            # ---- 可选：精确断言 retryFlag ----
            expected_retry = expected.get("expectedRetryFlag")
            if expected_retry is not None:
                actual_retry = body.get("retryFlag")
                assert actual_retry == expected_retry, (
                    f"[{tc_id}] retryFlag 不匹配: "
                    f"期望 {expected_retry}, 实际 {actual_retry}"
                )

            # ---- 可选：断言失败原因包含指定关键词（OR 语义，命中一个即通过） ----
            expected_keywords = expected.get("expectedFailReasonKeywords", [])
            if expected_keywords:
                fail_desc = body.get("failReasonDesc", "")
                resp_msg = data["header"].get("respMsg", "")
                combined = f"{fail_desc} {resp_msg}"
                matched = any(kw in combined for kw in expected_keywords)
                assert matched, (
                    f"[{tc_id}] 失败原因中缺少预期关键词 {expected_keywords}: "
                    f"failReasonDesc='{fail_desc}', respMsg='{resp_msg}'"
                )

    logger.info(f"[{tc_id}] ✓ 通过")


# ============================================================
# 幂等性专项测试（独立用例，不需 YAML 驱动）
# ============================================================

class TestIdempotency:
    """
    幂等性 (Idempotency) 专项测试

    验证 idempotencyToken 防重机制:
    - 同一 Token 多次请求返回相同结果
    - 不同 Token 各自独立处理
    """

    # ── 辅助：统一校验响应结构 ─────────────────────────────

    @staticmethod
    def _check_response(resp, context: str) -> dict:
        """
        校验 HTTP 响应状态码为 200 且业务数据包含 header/body

        自动拆壳：如果响应为标准 {code, message, data} 包装结构，
        则提取 data 层返回；否则返回原 JSON。
        返回的字典保证包含 header 和 body 字段。
        """
        assert resp.status_code == 200, (
            f"{context}: HTTP 状态码异常 (期望 200, 实际 {resp.status_code})\n"
            f"响应体: {resp.text[:500]}"
        )
        resp_json = resp.json()
        _assert_response_structure(
            resp_json,
            ["header", "body"],
            context=f"{context} 响应结构校验",
        )
        # 拆壳：提取业务数据层
        return resp_json.get("data", resp_json)

    # ── 用例 ────────────────────────────────────────────────

    @allure.feature("转账业务")
    @allure.story("幂等性验证")
    def test_same_token_returns_idempotent_response(
        self, api_session, transfer_url
    ):
        """
        用例: 同一 Token 发送两次请求，第二次应返回幂等结果而非重复扣款
        """
        token = generate_idempotency_key()
        payload = build_request_payload()
        payload["header"]["idempotencyToken"] = token

        # 第一次请求
        resp1 = BankAPI.transfer(api_session, transfer_url, payload, timeout=30)
        allure.attach(
            json.dumps(payload, indent=2, ensure_ascii=False),
            name="📤 Request Body - 第1次请求",
            attachment_type=allure.attachment_type.JSON,
        )
        json1 = self._check_response(resp1, "[幂等-同Token] 第1次请求")
        allure.attach(
            json.dumps(json1, indent=2, ensure_ascii=False),
            name="📥 Response Body - 第1次请求",
            attachment_type=allure.attachment_type.JSON,
        )

        # 第二次请求（使用相同的 token，刷新 nonce）
        payload["body"]["security"]["nonce"] = generate_nonce()
        resp2 = BankAPI.transfer(api_session, transfer_url, payload, timeout=30)
        allure.attach(
            json.dumps(payload, indent=2, ensure_ascii=False),
            name="📤 Request Body - 第2次请求",
            attachment_type=allure.attachment_type.JSON,
        )
        json2 = self._check_response(resp2, "[幂等-同Token] 第2次请求")
        allure.attach(
            json.dumps(json2, indent=2, ensure_ascii=False),
            name="📥 Response Body - 第2次请求",
            attachment_type=allure.attachment_type.JSON,
        )

        # 两次响应的 tranStatus 应一致
        status1 = json1["body"]["tranStatus"]
        status2 = json2["body"]["tranStatus"]
        assert status1 == status2, (
            f"幂等性失效: 第1次 status={status1}, 第2次 status={status2}"
        )

    @allure.feature("转账业务")
    @allure.story("幂等性验证")
    def test_different_tokens_independent(
        self, api_session, transfer_url
    ):
        """
        用例: 两个不同 Token 的请求应该各自独立处理
        """
        payload1 = build_request_payload()
        payload1["header"]["idempotencyToken"] = generate_idempotency_key()

        payload2 = build_request_payload()
        payload2["header"]["idempotencyToken"] = generate_idempotency_key()

        resp1 = BankAPI.transfer(api_session, transfer_url, payload1, timeout=30)
        allure.attach(
            json.dumps(payload1, indent=2, ensure_ascii=False),
            name="📤 Request Body - 请求1",
            attachment_type=allure.attachment_type.JSON,
        )
        json1 = self._check_response(resp1, "[幂等-不同Token] 请求1")
        allure.attach(
            json.dumps(json1, indent=2, ensure_ascii=False),
            name="📥 Response Body - 请求1",
            attachment_type=allure.attachment_type.JSON,
        )

        resp2 = BankAPI.transfer(api_session, transfer_url, payload2, timeout=30)
        allure.attach(
            json.dumps(payload2, indent=2, ensure_ascii=False),
            name="📤 Request Body - 请求2",
            attachment_type=allure.attachment_type.JSON,
        )
        json2 = self._check_response(resp2, "[幂等-不同Token] 请求2")
        allure.attach(
            json.dumps(json2, indent=2, ensure_ascii=False),
            name="📥 Response Body - 请求2",
            attachment_type=allure.attachment_type.JSON,
        )

        # 两个响应的受理流水号应该不同
        seq1 = json1["body"].get("acpTranSeqNo")
        seq2 = json2["body"].get("acpTranSeqNo")
        if json1["header"]["respCode"] == "000000" and \
           json2["header"]["respCode"] == "000000":
            assert seq1 != seq2, (
                f"不同 Token 却返回相同受理流水号: {seq1}"
            )

    @allure.feature("转账业务")
    @allure.story("幂等性验证")
    def test_idempotent_token_same_acp_seq_and_single_db_record(
        self, api_session, transfer_url, db_conn
    ):
        """
        用例: 幂等性严谨验证 — 相同 Token 返回相同受理流水号 + DB 仅一条流水

        验证步骤:
          1. 发起一笔小额转账（100 元），携带唯一 idempotencyToken
          2. 记录首次返回的 acpTranSeqNo
          3. 使用完全相同的 Token（刷新 nonce/时间戳/流水号后）再次发送
          4. 断言两次响应的 acpTranSeqNo 完全一致
          5. 查询数据库 transfer_record 表，断言该 Token 仅产生 1 条流水

        与 test_same_token_returns_idempotent_response 的区别:
          - 后者仅断言 tranStatus 一致（较宽松）
          - 本用例额外断言 acpTranSeqNo 一致 + 数据库唯一性（更严谨）
        """
        # ---- 1. 准备 ----
        token = generate_idempotency_key()

        # 使用小额转账，最大限度保证首次请求成功
        payload = build_request_payload({
            "body": {
                "transaction": {
                    "amount": 100.00,
                    "bizType": "1001",
                }
            }
        })
        payload["header"]["idempotencyToken"] = token

        # ---- 2. 第一次请求 ----
        logger.info(f"[幂等严谨] 发起第1次请求, token={token}")
        resp1 = BankAPI.transfer(api_session, transfer_url, payload, timeout=30)
        allure.attach(
            json.dumps(payload, indent=2, ensure_ascii=False),
            name="📤 Request Body - 第1次请求",
            attachment_type=allure.attachment_type.JSON,
        )
        json1 = self._check_response(resp1, "[幂等严谨] 第1次请求")
        allure.attach(
            json.dumps(json1, indent=2, ensure_ascii=False),
            name="📥 Response Body - 第1次请求",
            attachment_type=allure.attachment_type.JSON,
        )

        resp1_code = json1["header"]["respCode"]

        if resp1_code != "000000":
            pytest.skip(
                f"第1次请求未成功 (respCode={resp1_code}, "
                f"respMsg={json1['header'].get('respMsg')})，"
                f"无法验证幂等性"
            )

        acp_seq_1 = json1["body"]["acpTranSeqNo"]
        logger.info(f"[幂等严谨] 第1次成功, acpTranSeqNo={acp_seq_1}")

        # ---- 3. 第二次请求（相同 token，刷新所有动态字段） ----
        payload["header"]["tranSeqNo"] = generate_tran_seq_no(
            payload["header"].get("channelId", "MB")
        )
        payload["header"]["tranTimestamp"] = generate_timestamp()
        payload["body"]["security"]["nonce"] = generate_nonce()

        logger.info(f"[幂等严谨] 发起第2次请求, token={token} (相同)")
        resp2 = BankAPI.transfer(api_session, transfer_url, payload, timeout=30)
        allure.attach(
            json.dumps(payload, indent=2, ensure_ascii=False),
            name="📤 Request Body - 第2次请求",
            attachment_type=allure.attachment_type.JSON,
        )
        json2 = self._check_response(resp2, "[幂等严谨] 第2次请求")
        allure.attach(
            json.dumps(json2, indent=2, ensure_ascii=False),
            name="📥 Response Body - 第2次请求",
            attachment_type=allure.attachment_type.JSON,
        )

        # ---- 4. 断言 acpTranSeqNo 完全一致 ----
        acp_seq_2 = json2["body"].get("acpTranSeqNo")
        assert acp_seq_1 == acp_seq_2, (
            f"\n幂等性失效 — acpTranSeqNo 不一致:\n"
            f"  idempotencyToken: {token}\n"
            f"  第1次 acpTranSeqNo: {acp_seq_1}\n"
            f"  第2次 acpTranSeqNo: {acp_seq_2}\n"
            f"  期望: 两次返回完全相同的受理流水号"
        )
        logger.info(
            f"[幂等严谨] acpTranSeqNo 一致验证通过: {acp_seq_1}"
        )

        # ---- 5. 数据库唯一性校验 ----
        if db_conn is None:
            logger.warning(
                "[幂等严谨] 数据库不可用，跳过流水唯一性校验"
            )
            return

        cursor = None
        try:
            cursor = db_conn.cursor()

            # 查询该 idempotencyToken 产生的流水条数
            # 注意: 表名 transfer_record 和字段名 idempotency_key
            # 需与你的 Java 后端数据库设计一致，如有差异请调整
            cursor.execute(
                "SELECT COUNT(*) FROM transfer_record "
                "WHERE idempotency_key = %s",
                (token,),
            )
            row = cursor.fetchone()
            record_count = row[0] if row else 0

            assert record_count == 1, (
                f"\n幂等性防重失效 — 数据库流水数异常:\n"
                f"  idempotencyToken: {token}\n"
                f"  数据库记录数: {record_count}\n"
                f"  期望: 1 条\n"
                f"  说明: 同一 Token 产生了 {record_count} 条数据库流水，"
                f"幂等性防重机制未生效"
            )
            logger.info(
                f"[幂等严谨] 数据库唯一性验证通过: "
                f"token={token[:8]}... 仅 1 条流水"
            )

            # ---- 补充校验：确认该流水对应的 acpTranSeqNo 与接口返回一致 ----
            cursor.execute(
                "SELECT acp_tran_seq_no FROM transfer_record "
                "WHERE idempotency_key = %s",
                (token,),
            )
            row = cursor.fetchone()
            if row:
                db_acp_seq = row[0]
                assert db_acp_seq == acp_seq_1, (
                    f"\n幂等性数据一致性异常:\n"
                    f"  idempotencyToken: {token}\n"
                    f"  接口返回 acpTranSeqNo: {acp_seq_1}\n"
                    f"  数据库记录 acp_tran_seq_no: {db_acp_seq}"
                )
                logger.info(
                    f"[幂等严谨] DB 与接口 acpTranSeqNo 一致性验证通过"
                )

        except AssertionError:
            raise
        except Exception as e:
            logger.error(
                f"[幂等严谨] 数据库查询异常: {type(e).__name__}: {e}"
            )
        finally:
            if cursor:
                cursor.close()
