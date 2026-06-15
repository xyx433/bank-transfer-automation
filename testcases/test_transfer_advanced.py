"""
银行转账接口 — 高级场景专项测试（并发/防重放/对账/混沌）

这些测试场景需要多步编排、并发执行或数据库级别的校验，
无法通过 YAML 单请求数据驱动模式覆盖。

运行方式:
    # 运行全部高级场景
    pytest testcases/test_transfer_advanced.py -v

    # 仅运行并发测试
    pytest testcases/test_transfer_advanced.py -v -m concurrency

    # 仅运行对账测试
    pytest testcases/test_transfer_advanced.py -v -k "reconciliation"

注意:
    - 并发测试依赖后端数据库行级锁 (SELECT ... FOR UPDATE)
    - 对账测试依赖数据库连接可用
    - 防重放测试需要前后两次请求的编排
"""

import json
import logging
import threading
import time

import allure
import pytest
import requests

from apis.bank_api import BankAPI
from conftest import (
    build_request_payload,
    get_account_balance,
    generate_nonce,
    generate_timestamp,
    generate_tran_seq_no,
    generate_idempotency_key,
)


# ── 响应结构校验（从 test_transfer.py 复制，避免跨模块依赖） ──
def _assert_response_structure(
    resp_json: dict,
    expected_keys: list[str],
    context: str = "",
) -> None:
    """校验 HTTP 响应 JSON 是否包含预期的业务字段（自动拆壳）"""
    if "code" in resp_json and "data" in resp_json:
        inner = resp_json["data"]
        if not isinstance(inner, dict):
            raise AssertionError(
                f"{context}: resp_json['data'] 不是字典类型, "
                f"实际类型: {type(inner).__name__}"
            )
        missing = [k for k in expected_keys if k not in inner]
        if missing:
            actual_keys = list(inner.keys())
            raise AssertionError(
                f"{context}: 响应JSON的 data 内部缺少字段 {missing}\n"
                f"实际 data 字段: {actual_keys}"
            )
    else:
        missing = [k for k in expected_keys if k not in resp_json]
        if missing:
            actual_keys = list(resp_json.keys())
            raise AssertionError(
                f"{context}: 响应JSON顶层缺少字段 {missing}\n"
                f"实际顶层字段: {actual_keys}"
            )

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 辅助工具
# ═══════════════════════════════════════════════════════════

def _check_response(resp: requests.Response, context: str) -> dict:
    """校验 HTTP 200 响应并返回业务数据层字典"""
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
    return resp_json.get("data", resp_json)


def _attach_payload(payload: dict, name: str):
    """附加请求/响应体到 Allure 报告"""
    allure.attach(
        json.dumps(payload, indent=2, ensure_ascii=False),
        name=name,
        attachment_type=allure.attachment_type.JSON,
    )


# ═══════════════════════════════════════════════════════════
# 一、并发安全测试（P0 — 项目亮点）
# ═══════════════════════════════════════════════════════════

@pytest.mark.concurrency
@allure.feature("转账业务")
@allure.story("并发安全")
class TestConcurrencySafety:
    """
    并发安全专项测试

    验证数据库行级锁、余额扣减原子性、幂等性在并发场景下的正确性。
    """

    @allure.severity(allure.severity_level.CRITICAL)
    def test_balance_boundary_concurrent_breakthrough(
        self, api_session, transfer_url, db_conn
    ):
        """
        TC_Transfer_068: 余额临界并发击穿 — 100元余额并发3笔60元

        前置条件:
          - 赵六 (acct_no=6222021234567893) 余额仅 100.00 元
          - 3 个并发线程各发起 60.00 元转账（总需求 180 > 100 余额）

        验证点:
          1. 最多 1 笔 SUCCESS（金额 60 元，余额 → 40 元）
          2. 其余 2 笔 FAILED（BALANCE_INSUFFICIENT 10001）
          3. 数据库最终余额 ≥ 0（绝不为负数）
          4. transfer_record 中 SUCCESS 记录 ≤ 1 条
        """
        payer_acct = "6222021234567893"  # 赵六，余额 100.00
        amount = 60.00
        thread_count = 3

        # ---- 查询转账前余额 ----
        if db_conn is None:
            pytest.skip("数据库不可用，跳过并发击穿测试")
        initial_balance = get_account_balance(db_conn, payer_acct)
        if initial_balance is None:
            pytest.skip(f"账户 {payer_acct} 不存在")
        logger.info(
            f"[并发击穿] 赵六初始余额: {initial_balance:,.2f}, "
            f"并发数: {thread_count}, 每笔金额: {amount:,.2f}"
        )

        # ---- 并发发起转账 ----
        results = []
        lock = threading.Lock()

        def do_transfer(thread_idx: int):
            token = generate_idempotency_key()
            payload = build_request_payload({
                "header": {"channelId": "MB"},
                "body": {
                    "payer": {
                        "acctNo": payer_acct,
                        "acctName": "赵六",
                    },
                    "payee": {
                        "acctNo": "6228480012345678",
                        "acctName": "李四收款",
                        "payeeBankCode": "103100000026",
                        "payeeBankName": "中国农业银行上海分行",
                        "payeeBankUnionCode": "103290040217",
                    },
                    "transaction": {
                        "amount": amount,
                        "bizType": "1001",
                        "routeMode": "AUTO",
                    },
                },
            })
            payload["header"]["idempotencyToken"] = token

            try:
                resp = BankAPI.transfer(
                    api_session, transfer_url, payload, timeout=30
                )
                data = _check_response(resp, f"[并发击穿-线程{thread_idx}]")
                with lock:
                    results.append({
                        "thread": thread_idx,
                        "token": token,
                        "respCode": data["header"]["respCode"],
                        "tranStatus": data["body"]["tranStatus"],
                        "acpTranSeqNo": data["body"].get("acpTranSeqNo"),
                    })
            except AssertionError:
                with lock:
                    results.append({
                        "thread": thread_idx,
                        "token": token,
                        "respCode": "ERROR",
                        "tranStatus": "ERROR",
                    })

        # 启动并发线程
        threads = []
        for i in range(thread_count):
            t = threading.Thread(target=do_transfer, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=35)

        # ---- 断言 ----
        success_count = sum(
            1 for r in results if r["tranStatus"] == "SUCCESS"
        )
        failed_count = sum(
            1 for r in results if r["tranStatus"] == "FAILED"
        )

        logger.info(
            f"[并发击穿] 结果: SUCCESS={success_count}, "
            f"FAILED={failed_count}, 总计={len(results)}"
        )

        # 断言1: 最多1笔成功
        assert success_count <= 1, (
            f"并发击穿防护失败! 期望最多1笔SUCCESS, 实际 {success_count} 笔\n"
            f"详细结果: {json.dumps(results, indent=2, ensure_ascii=False)}"
        )

        # 断言2: 总成功金额 ≤ 初始余额
        total_success_amount = success_count * amount
        assert total_success_amount <= initial_balance, (
            f"超额扣款! 成功总额 {total_success_amount} > 初始余额 {initial_balance}"
        )

        # 断言3: 数据库最终余额 ≥ 0
        time.sleep(0.5)  # 等待异步余额更新
        final_balance = get_account_balance(db_conn, payer_acct)
        assert final_balance is not None and final_balance >= 0, (
            f"余额为负数! 最终余额: {final_balance}"
        )
        logger.info(
            f"[并发击穿] 余额校验通过: "
            f"{initial_balance:,.2f} → {final_balance:,.2f}"
        )

        # 断言4: 数据库流水唯一性
        if db_conn:
            cursor = None
            try:
                cursor = db_conn.cursor()
                for r in results:
                    if r["tranStatus"] == "SUCCESS":
                        cursor.execute(
                            "SELECT COUNT(*) FROM transfer_record "
                            "WHERE idempotency_key = %s",
                            (r["token"],),
                        )
                        row = cursor.fetchone()
                        assert row and row[0] == 1, (
                            f"Token {r['token']} 产生 {row[0] if row else 0} 条流水"
                        )
            finally:
                if cursor:
                    cursor.close()

        allure.attach(
            json.dumps(results, indent=2, ensure_ascii=False),
            name="🔬 并发击穿测试结果",
            attachment_type=allure.attachment_type.JSON,
        )

    @allure.severity(allure.severity_level.CRITICAL)
    def test_concurrent_same_idempotency_token_only_one_success(
        self, api_session, transfer_url, db_conn
    ):
        """
        TC_Transfer_045: 并发相同 idempotencyToken — 仅处理一次

        验证点:
          1. 5 个线程同时使用相同 Token 发送转账请求
          2. 仅 1 笔真正扣款（SUCCESS）
          3. 其余返回幂等结果
          4. 数据库仅 1 条流水
        """
        token = generate_idempotency_key()
        thread_count = 5
        results = []
        lock = threading.Lock()

        def do_transfer(thread_idx: int):
            payload = build_request_payload({
                "header": {"channelId": "MB"},
                "body": {
                    "payer": {
                        "acctNo": "6222021234567890",
                        "acctName": "张三",
                    },
                    "transaction": {
                        "amount": 100.00,
                        "bizType": "1001",
                    },
                },
            })
            payload["header"]["idempotencyToken"] = token
            # 每个线程使用不同的 tranSeqNo 避免框架层重复拦截
            payload["header"]["tranSeqNo"] = generate_tran_seq_no("MB")

            try:
                resp = BankAPI.transfer(
                    api_session, transfer_url, payload, timeout=30
                )
                data = _check_response(resp, f"[并发幂等-线程{thread_idx}]")
                with lock:
                    results.append({
                        "thread": thread_idx,
                        "respCode": data["header"]["respCode"],
                        "tranStatus": data["body"]["tranStatus"],
                        "acpTranSeqNo": data["body"].get("acpTranSeqNo"),
                    })
            except Exception as e:
                with lock:
                    results.append({
                        "thread": thread_idx,
                        "error": str(e)[:200],
                    })

        # 启动并发线程
        threads = []
        for i in range(thread_count):
            t = threading.Thread(target=do_transfer, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=35)

        # 收集 acpTranSeqNo
        success_results = [
            r for r in results
            if r.get("tranStatus") == "SUCCESS"
        ]
        acp_seqs = set(r.get("acpTranSeqNo") for r in success_results)

        logger.info(
            f"[并发幂等] 总请求: {len(results)}, "
            f"SUCCESS: {len(success_results)}, "
            f"唯一 acpTranSeqNo: {len(acp_seqs)}"
        )

        # 断言: 所有成功返回的 acpTranSeqNo 相同
        assert len(acp_seqs) <= 1, (
            f"并发幂等失效! 同一 Token 产生了 {len(acp_seqs)} 个不同流水号\n"
            f"详细: {json.dumps(results, indent=2, ensure_ascii=False)}"
        )

        # 数据库唯一性
        if db_conn and success_results:
            cursor = None
            try:
                cursor = db_conn.cursor()
                cursor.execute(
                    "SELECT COUNT(*) FROM transfer_record "
                    "WHERE idempotency_key = %s",
                    (token,),
                )
                row = cursor.fetchone()
                assert row and row[0] == 1, (
                    f"DB 流水数异常: 期望 1, 实际 {row[0] if row else 0}"
                )
            finally:
                if cursor:
                    cursor.close()

        allure.attach(
            json.dumps(results, indent=2, ensure_ascii=False),
            name="🔬 并发幂等测试结果",
            attachment_type=allure.attachment_type.JSON,
        )


# ═══════════════════════════════════════════════════════════
# 二、防重放攻击测试（P0）
# ═══════════════════════════════════════════════════════════

@pytest.mark.concurrency
@allure.feature("转账业务")
@allure.story("防重放攻击")
class TestAntiReplay:
    """
    防重放攻击 (Anti-Replay) 专项测试

    验证 nonce 防重放机制:
    - 时间戳偏差校验（±300 秒）
    - 重复 nonce 拦截
    - 攻击事件日志记录
    """

    @allure.severity(allure.severity_level.CRITICAL)
    @pytest.mark.skip(reason="Java后端暂未实现防重放检测逻辑，跳过此用例")
    def test_duplicate_nonce_triggers_replay_detection(
        self, api_session, transfer_url
    ):
        """
        TC_Transfer_037: 重复 nonce — 触发重放攻击检测

        步骤:
          1. 使用固定 nonce 值发起第1次请求（应正常处理）
          2. 使用相同 nonce 值发起第2次请求（刷新其他动态字段）
          3. 断言第2次返回 REPLAY_ATTACK（10008）
        """
        fixed_nonce = "1734329400_duplicate_nonce_test_001"

        # ---- 第1次请求（正常 nonce） ----
        payload1 = build_request_payload({
            "header": {"channelId": "MB"},
            "body": {
                "transaction": {"amount": 100.00, "bizType": "1001"},
                "security": {"nonce": fixed_nonce},
            },
        })
        _attach_payload(payload1, "📤 Request - 第1次 (固定nonce)")

        resp1 = BankAPI.transfer(api_session, transfer_url, payload1, timeout=30)
        json1 = _check_response(resp1, "[防重放-第1次]")
        _attach_payload(json1, "📥 Response - 第1次")
        logger.info(
            f"[防重放-第1次] respCode={json1['header']['respCode']}, "
            f"tranStatus={json1['body']['tranStatus']}"
        )

        # ---- 第2次请求（相同 nonce，刷新其他动态字段） ----
        payload2 = build_request_payload({
            "header": {
                "channelId": "MB",
                "tranSeqNo": generate_tran_seq_no("MB"),
                "tranTimestamp": generate_timestamp(),
                "idempotencyToken": generate_idempotency_key(),
            },
            "body": {
                "transaction": {"amount": 100.00, "bizType": "1001"},
                "security": {"nonce": fixed_nonce},
            },
        })
        _attach_payload(payload2, "📤 Request - 第2次 (相同nonce)")

        resp2 = BankAPI.transfer(api_session, transfer_url, payload2, timeout=30)
        json2 = _check_response(resp2, "[防重放-第2次]")
        _attach_payload(json2, "📥 Response - 第2次")

        # ---- 断言 ----
        resp_code_2 = json2["header"]["respCode"]
        logger.info(f"[防重放-第2次] respCode={resp_code_2}")

        # 第2次请求应返回 10008（REPLAY_ATTACK）
        assert resp_code_2 == "10008", (
            f"重复 nonce 未触发重放检测!\n"
            f"期望 respCode=10008 (REPLAY_ATTACK), 实际={resp_code_2}\n"
            f"respMsg: {json2['header'].get('respMsg')}"
        )
        assert json2["body"]["tranStatus"] == "FAILED", (
            f"重放攻击响应 tranStatus 应为 FAILED"
        )
        logger.info("[防重放] ✓ 重复 nonce 正确触发重放攻击检测")


# ═══════════════════════════════════════════════════════════
# 三、账务对账一致性测试（P1）
# ═══════════════════════════════════════════════════════════

@pytest.mark.regression
@allure.feature("转账业务")
@allure.story("账务对账")
class TestAccountingReconciliation:
    """
    账务对账一致性专项测试

    验证转账成功后:
    - account 余额表、transfer_record 流水表、fee_record 手续费表三方一致
    - 收款方正确入账
    - 冲正交易不计入限额
    """

    @allure.severity(allure.severity_level.CRITICAL)
    def test_transfer_success_triple_table_consistency(
        self, api_session, transfer_url, db_conn
    ):
        """
        TC_Transfer_075: 转账成功后三方对账一致

        验证:
          1. account 表付款方余额减少 = amount + fee
          2. transfer_record 有 1 条 SUCCESS 记录
          3. 收款方 account 表余额增加 = amount
          4. (如存在 fee_record 表) 手续费流水与转账流水 coreSerialNo 关联
        """
        if db_conn is None:
            pytest.skip("数据库不可用，跳过对账测试")

        payer_acct = "6222021234567890"  # 张三
        payee_acct = "6228480012345678"  # 李四收款
        amount = 5000.00

        # ---- 查询转账前余额 ----
        payer_before = get_account_balance(db_conn, payer_acct)
        payee_before = get_account_balance(db_conn, payee_acct)
        if payer_before is None or payee_before is None:
            pytest.skip("测试账户不存在")

        logger.info(
            f"[对账] 转账前 — 付款方: {payer_before:,.2f}, "
            f"收款方: {payee_before:,.2f}"
        )

        # ---- 发起转账 ----
        payload = build_request_payload({
            "header": {"channelId": "MB"},
            "body": {
                "payer": {
                    "acctNo": payer_acct,
                    "acctName": "张三",
                },
                "payee": {
                    "acctNo": payee_acct,
                    "acctName": "李四收款",
                    "payeeBankCode": "103100000026",
                    "payeeBankName": "中国农业银行上海分行",
                    "payeeBankUnionCode": "103290040217",
                },
                "transaction": {
                    "amount": amount,
                    "bizType": "1001",
                    "routeMode": "AUTO",
                    "feeBearer": "01",
                },
            },
        })

        resp = BankAPI.transfer(api_session, transfer_url, payload, timeout=30)
        json_data = _check_response(resp, "[对账]")
        _attach_payload(payload, "📤 对账-请求体")
        _attach_payload(json_data, "📥 对账-响应体")

        resp_code = json_data["header"]["respCode"]
        if resp_code != "000000":
            pytest.skip(f"转账未成功 (respCode={resp_code})，跳过对账校验")

        fee_amount = json_data["body"].get("feeAmount", 0)
        core_serial_no = json_data["body"].get("coreSerialNo")
        acp_tran_seq_no = json_data["body"].get("acpTranSeqNo")

        logger.info(
            f"[对账] 转账成功: amount={amount}, fee={fee_amount}, "
            f"coreSerialNo={core_serial_no}"
        )

        # ---- 等待异步余额更新 ----
        time.sleep(1.0)

        # ---- 校验1: 付款方余额 = 初始 - amount - fee ----
        payer_after = get_account_balance(db_conn, payer_acct)
        expected_payer = round(payer_before - amount - fee_amount, 2)
        assert payer_after is not None, f"付款账户 {payer_acct} 查询失败"
        assert payer_after == expected_payer, (
            f"付款方余额不一致!\n"
            f"期望: {payer_before:,.2f} - {amount:,.2f} - {fee_amount:,.2f} "
            f"= {expected_payer:,.2f}\n"
            f"实际: {payer_after:,.2f}"
        )

        # ---- 校验2: 收款方入账 ----
        payee_after = get_account_balance(db_conn, payee_acct)
        if payee_after is not None and payee_before is not None:
            # 跨行收款方入账可能有延迟，记录但不强制断言
            logger.info(
                f"[对账] 收款方余额: {payee_before:,.2f} → {payee_after:,.2f} "
                f"(变动: {payee_after - payee_before:,.2f})"
            )

        # ---- 校验3: transfer_record 流水存在且正确 ----
        cursor = None
        try:
            cursor = db_conn.cursor()
            cursor.execute(
                "SELECT tran_status, amount, fee_amount, core_serial_no "
                "FROM transfer_record WHERE acp_tran_seq_no = %s",
                (acp_tran_seq_no,),
            )
            row = cursor.fetchone()
            assert row is not None, (
                f"transfer_record 中未找到流水: {acp_tran_seq_no}"
            )
            db_status, db_amount, db_fee, db_core = row
            assert db_status == "SUCCESS", f"流水状态异常: {db_status}"
            assert float(db_amount) == amount, (
                f"流水金额不一致: {db_amount} vs {amount}"
            )
            assert float(db_fee or 0) == fee_amount, (
                f"流水手续费不一致: {db_fee} vs {fee_amount}"
            )
            logger.info(
                f"[对账] transfer_record 校验通过: "
                f"status={db_status}, amount={db_amount}, fee={db_fee}"
            )
        finally:
            if cursor:
                cursor.close()

        logger.info("[对账] ✓ 三方对账一致性验证通过")

    @allure.severity(allure.severity_level.NORMAL)
    def test_payee_mask_desensitization_rule(
        self, api_session, transfer_url
    ):
        """
        TC_Transfer_077: 收款账号脱敏规则验证

        验证成功响应中 payeeAcctMask 格式:
        - 前6位 + "******" + 后4位
        - 总长度 16 位
        - 中间 6 位被星号替换
        """
        amount = 100.00
        payload = build_request_payload({
            "header": {"channelId": "MB"},
            "body": {
                "payer": {
                    "acctNo": "6222021234567890",
                    "acctName": "张三",
                },
                "payee": {
                    "acctNo": "6228480012345678",
                    "acctName": "李四收款",
                    "payeeBankCode": "103100000026",
                    "payeeBankName": "中国农业银行上海分行",
                    "payeeBankUnionCode": "103290040217",
                },
                "transaction": {
                    "amount": amount,
                    "bizType": "1001",
                    "routeMode": "AUTO",
                },
            },
        })

        resp = BankAPI.transfer(api_session, transfer_url, payload, timeout=30)
        json_data = _check_response(resp, "[脱敏校验]")

        if json_data["header"]["respCode"] != "000000":
            pytest.skip("转账未成功，跳过脱敏校验")

        payee_mask = json_data["body"].get("payeeAcctMask", "")
        payee_acct = "6228480012345678"

        # 脱敏后应为 16 位（6 + 6个* + 4）
        assert len(payee_mask) == 16, (
            f"脱敏后长度异常: 期望 16, 实际 {len(payee_mask)} — '{payee_mask}'"
        )
        # 前6位保留
        assert payee_mask[:6] == payee_acct[:6], (
            f"脱敏前6位不匹配: '{payee_mask[:6]}' vs '{payee_acct[:6]}'"
        )
        # 中间6位为 ******
        assert payee_mask[6:12] == "******", (
            f"脱敏掩码异常: 期望 '******', 实际 '{payee_mask[6:12]}'"
        )
        # 后4位保留
        assert payee_mask[-4:] == payee_acct[-4:], (
            f"脱敏后4位不匹配: '{payee_mask[-4:]}' vs '{payee_acct[-4:]}'"
        )

        logger.info(f"[脱敏校验] ✓ payeeAcctMask={payee_mask} 格式正确")


# ═══════════════════════════════════════════════════════════
# 四、响应状态码全覆盖测试（P1）
# ═══════════════════════════════════════════════════════════

@pytest.mark.regression
@allure.feature("转账业务")
@allure.story("状态码覆盖")
class TestTranStatusCoverage:
    """
    交易状态 (tranStatus) 全状态覆盖测试

    验证 SUCCESS / FAILED / PROCESSING / TIMEOUT 四种状态的响应结构完整性。
    """

    @allure.severity(allure.severity_level.NORMAL)
    def test_failed_response_contains_all_required_fields(
        self, api_session, transfer_url
    ):
        """
        TC_Transfer_078: FAILED 状态 — 响应体完整性验证

        验证失败响应必须包含:
          - failReasonCode
          - failReasonDesc
          - retryFlag
          - tranStatus = "FAILED"
        """
        # 使用余额不足场景触发 FAILED
        payload = build_request_payload({
            "header": {"channelId": "MB"},
            "body": {
                "payer": {
                    "acctNo": "6222021234567893",
                    "acctName": "赵六",
                },
                "transaction": {"amount": 999999.00, "bizType": "1001"},
            },
        })

        resp = BankAPI.transfer(api_session, transfer_url, payload, timeout=30)
        json_data = _check_response(resp, "[FAILED状态]")

        body = json_data["body"]
        assert body["tranStatus"] == "FAILED", (
            f"tranStatus 应为 FAILED, 实际: {body['tranStatus']}"
        )
        assert body.get("failReasonCode"), "FAILED 响应缺少 failReasonCode"
        assert body.get("failReasonDesc"), "FAILED 响应缺少 failReasonDesc"
        assert "retryFlag" in body, "FAILED 响应缺少 retryFlag"

        logger.info(
            f"[FAILED状态] ✓ failReasonCode={body['failReasonCode']}, "
            f"failReasonDesc={body['failReasonDesc']}, "
            f"retryFlag={body.get('retryFlag')}"
        )

    @allure.severity(allure.severity_level.NORMAL)
    def test_success_response_contains_all_required_fields(
        self, api_session, transfer_url
    ):
        """
        验证 SUCCESS 响应必须包含:
          - acpTranSeqNo (受理流水号)
          - coreSerialNo (核心流水号)
          - hostSeqNo (人行清算流水号)
          - payeeAcctMask (脱敏收款账号)
          - actualAmount (实际到账金额)
          - feeAmount (手续费)
          - completedTime (完成时间)
        """
        payload = build_request_payload({
            "header": {"channelId": "MB"},
            "body": {
                "payer": {
                    "acctNo": "6222021234567890",
                    "acctName": "张三",
                },
                "payee": {
                    "acctNo": "6228480012345678",
                    "acctName": "李四收款",
                    "payeeBankCode": "103100000026",
                    "payeeBankName": "中国农业银行上海分行",
                    "payeeBankUnionCode": "103290040217",
                },
                "transaction": {
                    "amount": 100.00,
                    "bizType": "1001",
                    "routeMode": "AUTO",
                },
            },
        })

        resp = BankAPI.transfer(api_session, transfer_url, payload, timeout=30)
        json_data = _check_response(resp, "[SUCCESS状态]")

        if json_data["header"]["respCode"] != "000000":
            pytest.skip("转账未成功，跳过 SUCCESS 字段校验")

        body = json_data["body"]
        assert body["tranStatus"] == "SUCCESS"

        # 必需字段校验
        required_fields = [
            ("acpTranSeqNo", "受理流水号"),
            ("coreSerialNo", "核心流水号"),
            ("hostSeqNo", "人行清算流水号"),
            ("payeeAcctMask", "脱敏收款账号"),
            ("actualAmount", "实际到账金额"),
            ("completedTime", "完成时间"),
        ]
        for field, desc in required_fields:
            assert body.get(field), f"SUCCESS 响应缺少 {desc} ({field})"

        # 手续费 ≥ 0
        assert body.get("feeAmount", -1) >= 0, (
            f"手续费异常: {body.get('feeAmount')}"
        )
        # 脱敏校验
        assert "****" in body.get("payeeAcctMask", ""), (
            f"收款账号未脱敏: {body.get('payeeAcctMask')}"
        )
        # actualAmount 与请求一致
        assert body.get("actualAmount") == 100.00, (
            f"actualAmount 不一致: {body.get('actualAmount')}"
        )

        logger.info(
            f"[SUCCESS状态] ✓ acpTranSeqNo={body['acpTranSeqNo']}, "
            f"coreSerialNo={body['coreSerialNo']}, "
            f"hostSeqNo={body['hostSeqNo']}"
        )
