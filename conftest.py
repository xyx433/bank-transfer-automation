"""
银行转账接口自动化测试 - Pytest 全局配置

本文件封装了:
- 被测接口的 BaseUrl
- 可复用的 HTTP Session fixture
- 请求报文构建工具函数
- 动态字段自动生成（流水号、幂等Token、时间戳）
"""

import glob as glob_module
import os
import time
import uuid
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import allure
import pytest
import requests
import yaml

try:
    import pymysql
    _PYMYSQL_AVAILABLE = True
except ImportError:  # pragma: no cover
    pymysql = None
    _PYMYSQL_AVAILABLE = False

logger = logging.getLogger(__name__)


# ============================================================
# 全局常量
# ============================================================

BASE_URL = "http://localhost:8080"  # 接口地址
TRANSFER_ENDPOINT = "/api/v1/transfer"  # 接口地址

# 中国时区 UTC+8
CST = timezone(timedelta(hours=8))

# 交易渠道限额配置（元）
CHANNEL_LIMITS = {
    "MB": {"single": 50000, "daily": 200000},   # 手机银行
    "EB": {"single": 500000, "daily": 2000000},  # 网上银行
    "WC": {"single": 10000, "daily": 50000},     # 微信小程序
}

# 错误码映射
ERROR_CODES = {
    "SUCCESS": "000000",
    "BALANCE_INSUFFICIENT": "10001",
    "DAILY_LIMIT_EXCEEDED": "10002",
    "SINGLE_LIMIT_EXCEEDED": "10003",
    "ACCOUNT_STATUS_ABNORMAL": "10004",
    "AML_SUSPICIOUS": "10005",
    "PAYEE_BLOCKED": "10006",
    "AUTH_FAILED": "10007",
    "REPLAY_ATTACK": "10008",
    "ROUTE_UNAVAILABLE": "10009",
    "PAYEE_INFO_MISMATCH": "10010",
    "FEE_CALC_ERROR": "10011",
    "REMIT_INFO_BLOCKED": "10012",
}

# 数据库连接配置（可通过环境变量覆盖）
DB_CONFIG = {
    "host": os.environ.get("BANK_DB_HOST", "localhost"),
    "port": int(os.environ.get("BANK_DB_PORT", "3306")),
    "user": os.environ.get("BANK_DB_USER", "root"),
    "password": os.environ.get("BANK_DB_PASSWORD", "518089"),
    # 默认数据库名；如实际名称不同，请设置环境变量 BANK_DB_NAME 覆盖
    "database": os.environ.get("BANK_DB_NAME", "bank_core"),
    "charset": "utf8mb4",
    "connect_timeout": 5,
}


# ============================================================
# Allure 失败上下文数据容器
# ============================================================

@dataclass
class TestContext:
    """
    每个测试用例的运行时元数据容器

    测试函数通过 test_context fixture 获取本对象，
    在执行过程中填充请求/响应/数据库快照。
    测试失败时，pytest_runtest_makereport 钩子自动将
    容器内的所有数据附加到 Allure 报告中。

    使用方式:
        def test_xxx(api_session, transfer_url, test_context):
            payload = build_request_payload(...)
            response = api_post_with_context(
                api_session, transfer_url, payload, test_context
            )
            test_context.add_db_snapshot("付款方-转账前", acct_no, balance)
    """
    request_payload: dict | None = None
    response_status_code: int | None = None
    response_body: dict | str | None = None
    response_headers: dict | None = None
    db_snapshots: list[dict] = field(default_factory=list)
    elapsed_seconds: float | None = None

    def add_db_snapshot(self, label: str, acct_no: str, balance: float | None):
        """记录一次数据库余额快照"""
        self.db_snapshots.append({
            "label": label,
            "acct_no": acct_no,
            "balance": balance,
        })


# 告知 pytest 这不是一个测试类（避免 PytestCollectionWarning）
TestContext.__test__ = False


# ============================================================
# 工具函数
# ============================================================

def generate_tran_seq_no(channel_id: str = "MB") -> str:
    """
    生成全局唯一交易流水号

    格式: YYYYMMDD + PIT + 2位渠道码 + 8位序号
    示例: 20260611PITMB00000001
    """
    now = datetime.now(CST)
    date_part = now.strftime("%Y%m%d")
    # 使用时间微秒 + 随机数作为序号，确保测试场景下不重复
    seq = str(uuid.uuid4().int)[:8]
    return f"{date_part}PIT{channel_id}{seq}"


def generate_idempotency_key() -> str:
    """生成全局幂等Token（UUID v4 格式）"""
    return str(uuid.uuid4())


def generate_nonce() -> str:
    """生成防重放随机数，格式: {timestamp}_{randomString}"""
    ts = str(int(datetime.now(CST).timestamp()))
    rand = str(uuid.uuid4().int)[:16]
    return f"{ts}_{rand}"


def generate_timestamp() -> str:
    """生成 ISO 8601 格式交易时间戳（带时区偏移）"""
    return datetime.now(CST).isoformat(timespec="milliseconds")


# ============================================================
# 默认请求模板
# ============================================================

def get_default_request_body() -> dict:
    """
    返回一份合法的默认请求体模板

    各测试用例可以在该模板基础上通过 deep_merge 覆盖特定字段，
    避免每个用例都写完整的请求体。
    """
    return {
        "header": {
            "tranSeqNo": generate_tran_seq_no("MB"),
            "channelId": "MB",
            "tranTimestamp": generate_timestamp(),
            "version": "1.0.0",
            "idempotencyToken": generate_idempotency_key(),
        },
        "body": {
            "payer": {
                "acctNo": "6222021234567890",
                "acctName": "张三",
                "idType": "01",
                "idNo": "310101199001011234",
                "payerBankCode": "102100099996",
                "payerBankName": "中国工商银行北京分行",
            },
            "payee": {
                "acctNo": "6228480012345678",
                "acctName": "李四收款",
                "payeeBankCode": "103100000026",
                "payeeBankName": "中国农业银行上海分行",
                "payeeBankUnionCode": "103290040217",
            },
            "transaction": {
                "amount": 5000.00,
                "currencyCode": "CNY",
                "bizType": "1001",
                "purposeCode": "01",
                "remitInfo": "货款转账",
                "routeMode": "AUTO",
                "feeBearer": "01",
            },
            "security": {
                "smsCode": "834291",
                "tradePwdEnc": "Sm4Encrypted&Base64==",
                "deviceFingerprint": "fp_ios_16_xr_abc123",
                "faceToken": "liveBodyToken_23984729384",
                "nonce": generate_nonce(),
            },
            "extendInfo": {
                "clientIp": "202.106.0.20",
                "macAddress": "AA:BB:CC:DD:EE:FF",
                "gpsCoordinate": {
                    "longitude": 116.4074,
                    "latitude": 39.9042,
                },
                "terminalId": "T20230001",
                "terminalType": "iOS_16.0_iPhone14",
            },
        },
        "signature": "Base64Encoded_RSAwithSHA256_Signature_Placeholder",
    }


def deep_merge(base: dict, override: dict) -> dict:
    """
    深度合并两个字典

    - override 中的标量值直接覆盖 base
    - override 中的嵌套字典递归合并
    - override 中的 None 值表示删除该字段
    """
    result = base.copy()
    for key, value in override.items():
        if value is None:
            result.pop(key, None)
        elif key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def api_post_with_context(
    session: requests.Session,
    url: str,
    payload: dict,
    context: TestContext,
    **kwargs,
) -> requests.Response:
    """
    发送 POST 请求并自动将请求/响应捕获到 TestContext

    增强功能:
      1. 请求前 — INFO 日志记录 method/URL/金额/付款方/收款方/超时
      2. 请求后 — INFO 日志记录 HTTP 状态码/耗时/响应摘要
      3. 异常时 — ERROR 日志记录完整异常信息
      4. 所有数据写入 TestContext 供 Allure 失败诊断

    Usage:
        response = api_post_with_context(
            api_session, transfer_url, payload, test_context,
            timeout=30
        )
    """
    context.request_payload = payload

    # ── 请求前日志 ──
    amount = payload.get("body", {}).get("transaction", {}).get("amount", "?")
    payer = payload.get("body", {}).get("payer", {}).get("acctNo", "?")
    payee = payload.get("body", {}).get("payee", {}).get("acctNo", "?")
    timeout_val = kwargs.get("timeout", "default")

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
        response = session.post(url, json=payload, **kwargs)
        elapsed = round(time.perf_counter() - start, 4)
        context.elapsed_seconds = elapsed

        context.response_status_code = response.status_code
        context.response_headers = dict(response.headers)

        try:
            context.response_body = response.json()
        except Exception:
            context.response_body = response.text[:5000]

        # ── 请求后日志（成功收到 HTTP 响应） ──
        resp_summary = ""
        if isinstance(context.response_body, dict):
            code = context.response_body.get("code", "")
            msg = context.response_body.get("message", "")
            if code or msg:
                resp_summary = f" | code={code} msg={msg}"
        logger.info(
            f"← HTTP {response.status_code} | "
            f"elapsed={elapsed:.3f}s"
            f"{resp_summary}"
        )

        return response

    except Exception as exc:
        elapsed = round(time.perf_counter() - start, 4)
        context.elapsed_seconds = elapsed

        logger.error(
            f"✗ POST {url} 请求失败 | "
            f"elapsed={elapsed:.3f}s | "
            f"{type(exc).__name__}: {exc}"
        )
        raise


# ── 城市坐标映射表 ──
# 格式: { "城市名": {"longitude": "经度", "latitude": "纬度"} }
# 新增城市只需在此注册一行
_CITY_COORDINATES = {
    "信阳": {"longitude": "114.0646", "latitude": "32.1282"},
}


def _replace_time_location(data: Any) -> None:
    """
    递归遍历字典/列表，替换字符串值中的占位符（原地修改）。

    支持三种占位符语法 ——————————————————————————————

    1. <location:城市名>
       按字段名语义替换为对应城市的经纬度坐标。
       如果键名含 "longitude" → 经度值；
       如果键名含 "latitude"  → 纬度值。

       示例:
         YAML:  longitude: "<location:信阳>"
         结果:  "longitude": "114.0646"

         YAML:  latitude: "<location:信阳>"
         结果:  "latitude": "32.1282"

    2. <time:格式字符串>
       使用 datetime.now(CST).strftime(格式字符串) 替换。
       格式字符串为 Python strftime 标准格式。

       示例:
         YAML:  customDate: "<time:%Y-%m-%d>"
         结果:  "customDate": "2026-06-13"

         YAML:  timestampMs: "<time:%Y-%m-%dT%H:%M:%S>"
         结果:  "timestampMs": "2026-06-13T14:30:05"

    3. <time_location>（向后兼容旧版）
       键名含 "longitude" → 替换为 114.0646
       键名含 "latitude"  → 替换为 32.1282

    支持嵌套 dict 和 list 的深度遍历。

    Args:
        data: 待处理的字典或列表（原地修改）
    """
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str):
                # ── 1. <location:城市名> 占位符 ──
                loc_match = re.match(r"^<location:(.+)>$", value.strip())
                if loc_match:
                    city = loc_match.group(1).strip()
                    coords = _CITY_COORDINATES.get(city)
                    if coords:
                        key_lower = key.lower()
                        if "longitude" in key_lower:
                            data[key] = coords["longitude"]
                        elif "latitude" in key_lower:
                            data[key] = coords["latitude"]
                    continue

                # ── 2. <time:格式> 占位符 ──
                time_match = re.match(r"^<time:(.+)>$", value.strip())
                if time_match:
                    fmt = time_match.group(1).strip()
                    data[key] = datetime.now(CST).strftime(fmt)
                    continue

                # ── 3. 向后兼容: <time_location> ──
                if "<time_location>" in value:
                    key_lower = key.lower()
                    if "longitude" in key_lower:
                        data[key] = value.replace("<time_location>", "114.0646")
                    elif "latitude" in key_lower:
                        data[key] = value.replace("<time_location>", "32.1282")

            elif isinstance(value, (dict, list)):
                _replace_time_location(value)

    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                _replace_time_location(item)


def build_request_payload(overrides: dict | None = None) -> dict:
    """
    构建完整的请求报文

    以默认模板为基础，通过 overrides 覆盖差异字段。
    自动刷新时间敏感字段（tranSeqNo / idempotencyToken / nonce / timestamp）。

    使用方式:
        payload = build_request_payload({
            "body": {
                "transaction": {"amount": 1.00}
            }
        })
    """
    base = get_default_request_body()

    # ---- 总是刷新动态字段，避免重复使用 ----
    base["header"]["tranSeqNo"] = generate_tran_seq_no(
        base["header"].get("channelId", "MB")
    )
    base["header"]["tranTimestamp"] = generate_timestamp()
    base["header"]["idempotencyToken"] = generate_idempotency_key()
    base["body"]["security"]["nonce"] = generate_nonce()

    if overrides:
        base = deep_merge(base, overrides)

    # ---- 递归替换 <time_location> 占位符为地理坐标 ----
    _replace_time_location(base)

    return base


# ============================================================
# 数据库工具函数
# ============================================================

def _check_pymysql():
    """检查 pymysql 是否可用，不可用则抛出明确提示"""
    if not _PYMYSQL_AVAILABLE:
        raise ImportError(
            "pymysql 未安装，无法进行数据库校验。"
            "请执行: pip install pymysql"
        )


def create_db_connection(config: dict | None = None):
    """
    创建数据库连接

    Args:
        config: 数据库连接配置字典，为 None 时使用全局 DB_CONFIG

    Returns:
        pymysql.Connection 对象

    Raises:
        pymysql.MySQLError: 连接失败
    """
    _check_pymysql()
    cfg = config or DB_CONFIG
    conn = pymysql.connect(**cfg)
    # 启用 autocommit，确保每次查询都能看到 Java 后端最新提交的数据
    # 避免 REPEATABLE READ 隔离级别下的快照滞后问题
    conn.autocommit(True)
    logger.info(
        f"数据库连接成功: {cfg['host']}:{cfg['port']}/{cfg['database']}"
    )
    return conn


def get_account_balance(db_conn, acct_no: str) -> float | None:
    """
    查询指定账户的当前余额

    Args:
        db_conn: pymysql Connection 对象
        acct_no:  账户号码

    Returns:
        账户余额（float），账户不存在时返回 None

    Raises:
        pymysql.MySQLError: 查询异常
    """
    cursor = None
    try:
        cursor = db_conn.cursor()
        cursor.execute(
            "SELECT balance FROM account WHERE acct_no = %s",
            (acct_no,),
        )
        row = cursor.fetchone()
        if row is None:
            logger.warning(f"账户 {acct_no} 在数据库中不存在")
            return None
        balance = float(row[0])
        logger.debug(f"查询余额: acct_no={acct_no}, balance={balance}")
        return balance
    finally:
        if cursor:
            cursor.close()


def execute_sql_file(db_conn, file_path: str) -> tuple[int, list[str]]:
    """
    执行 SQL 脚本文件

    解析 .sql 文件并逐条执行。跳过空语句和纯注释行。
    遇到执行错误时记录并继续（软降级策略），不中断后续 SQL。

    Args:
        db_conn:   pymysql Connection 对象
        file_path: SQL 文件的绝对路径

    Returns:
        (success_count, errors_list)
          - success_count: 成功执行的语句数
          - errors_list:   失败语句的描述列表

    Raises:
        FileNotFoundError: SQL 文件不存在
    """
    with open(file_path, "r", encoding="utf-8") as f:
        sql_content = f.read()

    # 拆分为独立语句：按分号分割，过滤空行和纯注释
    statements = []
    for raw in sql_content.split(";"):
        stmt = raw.strip()
        if not stmt:
            continue
        # 跳过纯注释行（不包含任何 SQL 关键字）
        if stmt.startswith("--"):
            continue
        statements.append(stmt)

    cursor = None
    success_count = 0
    errors = []

    try:
        cursor = db_conn.cursor()
        for stmt in statements:
            try:
                cursor.execute(stmt)
                success_count += 1
            except Exception as e:
                # 截取 SQL 前 120 字符用于日志
                preview = stmt.replace("\n", " ")[:120]
                err_msg = (
                    f"SQL 执行失败 [{file_path}]: {e}\n"
                    f"  语句: {preview}..."
                )
                logger.error(err_msg)
                errors.append(err_msg)

        db_conn.commit()
    finally:
        if cursor:
            cursor.close()

    return success_count, errors


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="session")
def session_db_conn():
    """
    数据库连接 fixture（session 级别，全程复用）

    用于 session 级别的环境重置/清理操作。
    连接成功返回 pymysql.Connection，失败返回 None（软降级）。
    """
    if not _PYMYSQL_AVAILABLE:
        logger.warning("pymysql 未安装，跳过 session 级别数据库操作")
        yield None
        return

    conn = None
    try:
        conn = create_db_connection()
        logger.info("Session 级别数据库连接已建立（用于环境重置/清理）")
    except Exception as e:
        logger.warning(
            f"Session 级别数据库连接失败，将跳过自动重置/清理: {e}"
        )
        yield None
        return

    try:
        yield conn
    finally:
        try:
            conn.close()
            logger.info("Session 级别数据库连接已关闭")
        except Exception as e:
            logger.warning(f"关闭 Session 数据库连接时异常: {e}")


@pytest.fixture(scope="session", autouse=True)
def environment_reset(session_db_conn):
    """
    🔑 企业级环境自动化：测试前自动重置，测试后自动清理

    Setup (所有测试开始前):
      执行 sql/reset_test_accounts.sql → 重置测试账户到初始状态

    Teardown (所有测试结束后):
      执行 sql/cleanup_transfer_records.sql → 清理本次产生的测试流水

    设计原则:
      - 软降级: 数据库不可用时仅警告，不中断测试流程
      - 幂等性: reset 脚本使用 INSERT ... ON DUPLICATE KEY UPDATE
      - 隔离性: cleanup 脚本仅删除带测试标记(PIT)的数据
      - 可配置: SQL 文件路径可通过环境变量覆盖
    """
    # ── 自动重置开关（环境变量 BANK_AUTO_RESET=false 可禁用） ──
    auto_reset_enabled = os.environ.get("BANK_AUTO_RESET", "true").lower() != "false"
    auto_cleanup_enabled = os.environ.get("BANK_AUTO_CLEANUP", "true").lower() != "false"

    if not auto_reset_enabled and not auto_cleanup_enabled:
        logger.info("环境自动重置/清理已通过环境变量禁用")
        yield
        return

    # 确定 SQL 文件路径
    project_root = Path(__file__).resolve().parent
    sql_dir = os.environ.get("BANK_SQL_DIR", str(project_root / "sql"))
    reset_script = os.environ.get(
        "BANK_RESET_SQL", os.path.join(sql_dir, "reset_test_accounts.sql")
    )
    cleanup_script = os.environ.get(
        "BANK_CLEANUP_SQL", os.path.join(sql_dir, "cleanup_transfer_records.sql")
    )

    # ────────────────────────────────────────────
    # SETUP: 测试前重置
    # ────────────────────────────────────────────
    if auto_reset_enabled and session_db_conn is not None:
        logger.info("=" * 56)
        logger.info("🔧 [环境重置] 开始执行测试环境自动重置...")
        logger.info("=" * 56)

        if os.path.exists(reset_script):
            success, errors = execute_sql_file(session_db_conn, reset_script)
            logger.info(
                f"[环境重置] 完成: {success} 条语句执行成功"
                + (f", {len(errors)} 条失败 ⚠️" if errors else " ✓")
            )
            for err in errors:
                logger.warning(f"[环境重置] {err}")
        else:
            logger.warning(
                f"[环境重置] 脚本不存在: {reset_script}\n"
                f"  请确认 sql/reset_test_accounts.sql 文件存在且配置正确。\n"
                f"  可通过环境变量 BANK_RESET_SQL 指定自定义路径。"
            )
    elif auto_reset_enabled:
        logger.warning(
            "[环境重置] 数据库不可用，跳过自动重置。"
            "请手动确保测试账户处于初始状态。"
        )

    # ── 移交控制权给测试用例 ──
    yield

    # ────────────────────────────────────────────
    # TEARDOWN: 测试后清理
    # ────────────────────────────────────────────
    if auto_cleanup_enabled and session_db_conn is not None:
        logger.info("=" * 56)
        logger.info("🧹 [环境清理] 开始清理测试流水数据...")
        logger.info("=" * 56)

        if os.path.exists(cleanup_script):
            success, errors = execute_sql_file(session_db_conn, cleanup_script)
            logger.info(
                f"[环境清理] 完成: {success} 条语句执行成功"
                + (f", {len(errors)} 条失败 ⚠️" if errors else " ✓")
            )
            for err in errors:
                logger.warning(f"[环境清理] {err}")
        else:
            logger.warning(
                f"[环境清理] 脚本不存在: {cleanup_script}"
            )

    logger.info("[环境自动化] 全部完成")

@pytest.fixture(scope="session")
def base_url() -> str:
    """返回被测接口的基础 URL"""
    return BASE_URL


@pytest.fixture(scope="session")
def transfer_url(base_url: str) -> str:
    """返回转账接口的完整 URL"""
    return f"{base_url}{TRANSFER_ENDPOINT}"


@pytest.fixture(scope="session")
def api_session() -> requests.Session:
    """
    创建一个配置好 BaseUrl 的 requests Session（会话级别复用）

    - 自动附带 Content-Type: application/json
    - 连接池复用，减少 TCP 握手开销
    """
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json; charset=UTF-8",
        "Accept": "application/json",
        "User-Agent": "BankAITestPlatform/1.0",
    })
    return session


@pytest.fixture
def default_payload() -> dict:
    """返回一份带新鲜动态字段的默认请求体，每个用例独立"""
    return build_request_payload()


@pytest.fixture
def db_conn():
    """
    数据库连接 fixture（函数级别，每个用例独立连接）

    - 连接成功返回 pymysql.Connection 对象
    - 连接失败/模块未安装时返回 None（软降级，不中断测试）
    - 用例结束后自动关闭连接
    """
    if not _PYMYSQL_AVAILABLE:
        logger.warning("pymysql 未安装，跳过数据库校验（pip install pymysql）")
        yield None
        return

    conn = None
    try:
        conn = create_db_connection()
        logger.debug("数据库连接已建立，将启用余额校验")
    except Exception as e:
        logger.warning(
            f"数据库连接失败，本次用例将跳过余额校验: {e}"
        )
        yield None
        return

    try:
        yield conn
    finally:
        try:
            conn.close()
            logger.debug("数据库连接已关闭")
        except Exception as e:
            logger.warning(f"关闭数据库连接时异常: {e}")


@pytest.fixture
def test_context() -> TestContext:
    """
    每个测试用例独立的 Allure 失败上下文容器

    测试函数在执行过程中将关键数据写入本容器:
      - test_context.request_payload  → 请求报文
      - test_context.response_body    → 响应报文
      - test_context.db_snapshots     → 数据库余额快照

    测试失败时，pytest_runtest_makereport 钩子自动将
    容器中所有数据附加到 Allure 报告中。

    无需在测试代码中手动调用 allure.attach()。
    """
    ctx = TestContext()
    yield ctx


# ============================================================
# Pytest 配置
# ============================================================

def _attach_failure_context_to_allure(ctx: TestContext, nodeid: str):
    """
    将 TestContext 中的所有数据格式化为附件，写入 Allure 报告

    仅在被测用例失败时调用。

    附件列表：
      1. 📤 Request Payload    — 完整 JSON 请求报文
      2. 📥 Response           — HTTP 状态码 + 完整 JSON 响应
      3. 📊 DB Snapshots       — 数据库余额快照
      4. ⏱️  Timing             — 接口响应耗时
    """
    # ── 附件 1: 请求报文 ──
    if ctx.request_payload is not None:
        # 脱敏处理：隐藏安全敏感字段
        safe_payload = json.loads(json.dumps(ctx.request_payload))
        if "body" in safe_payload and "security" in safe_payload["body"]:
            sec = safe_payload["body"]["security"]
            if "smsCode" in sec:
                sec["smsCode"] = "******"
            if "tradePwdEnc" in sec:
                sec["tradePwdEnc"] = "******"
            if "faceToken" in sec:
                sec["faceToken"] = "******"

        allure.attach(
            json.dumps(safe_payload, indent=2, ensure_ascii=False),
            name="🔴 请求报文",
            attachment_type=allure.attachment_type.JSON,
        )

    # ── 附件 2: 响应报文 ──
    if ctx.response_body is not None:
        resp_body_str = (
            json.dumps(ctx.response_body, indent=2, ensure_ascii=False)
            if isinstance(ctx.response_body, dict)
            else str(ctx.response_body)
        )
        allure.attach(
            resp_body_str,
            name="🟢 响应报文",
            attachment_type=allure.attachment_type.JSON
            if isinstance(ctx.response_body, dict)
            else allure.attachment_type.TEXT,
        )

        # 响应头（精简版）
        if ctx.response_headers:
            important_headers = {
                k: v for k, v in ctx.response_headers.items()
                if k.lower() in (
                    "content-type", "x-request-id", "x-trace-id",
                    "x-rate-limit-remaining", "x-response-time",
                )
            }
            if important_headers:
                allure.attach(
                    json.dumps(important_headers, indent=2, ensure_ascii=False),
                    name="📋 Response Headers (关键响应头)",
                    attachment_type=allure.attachment_type.JSON,
                )

    # ── 附件 3: 数据库快照 ──
    if ctx.db_snapshots:
        lines = []
        lines.append(f"{'标签':<20} {'账户号码':<22} {'余额':>16}")
        lines.append("-" * 60)
        for snap in ctx.db_snapshots:
            balance_str = (
                f"{snap['balance']:,.2f}"
                if snap["balance"] is not None
                else "N/A"
            )
            lines.append(
                f"{snap['label']:<20} {snap['acct_no']:<22} {balance_str:>16}"
            )
        snapshot_report = "\n".join(lines)

        allure.attach(
            snapshot_report,
            name="📊 DB Balance Snapshots (数据库余额快照)",
            attachment_type=allure.attachment_type.TEXT,
        )

    # ── 附件 4: 耗时 ──
    if ctx.elapsed_seconds is not None:
        allure.attach(
            f"接口响应耗时: {ctx.elapsed_seconds:.3f} 秒",
            name="⏱️ 耗时",
            attachment_type=allure.attachment_type.TEXT,
        )

    # ── 附件 5: 失败上下文摘要 ──
    summary_lines = [
        f"测试用例: {nodeid}",
        f"响应状态码: {ctx.response_status_code or 'N/A'}",
        f"接口耗时: {ctx.elapsed_seconds:.3f}s" if ctx.elapsed_seconds else "N/A",
        f"数据库快照数: {len(ctx.db_snapshots)}",
        "",
        "💡 提示: 请结合以上 Request / Response / DB Snapshot 附件进行故障定位。",
    ]
    allure.attach(
        "\n".join(summary_lines),
        name="🔍 Failure Context Summary (失败上下文摘要)",
        attachment_type=allure.attachment_type.TEXT,
    )


def pytest_runtest_makereport(item, call):
    """
    🔑 企业级报告钩子：失败自动附加 Allure 上下文 + 记录异常日志

    功能 A — Allure 附件（升级三）:
      测试失败时自动将 Request/Response/DB 快照附加到 Allure 报告

    功能 B — 异常日志（升级四）:
      测试失败时自动记录完整 Traceback 到日志文件,
      包含测试用例 nodeid、失败阶段、异常类型与消息。
      成功时记录 PASS 状态（DEBUG 级别）。
    """
    if call.when == "call":
        if call.excinfo is not None:
            # ── B. 失败日志（ERROR 级别，含完整 traceback） ──
            exc_type = call.excinfo.type.__name__ if call.excinfo.type else "Unknown"
            exc_msg = str(call.excinfo.value) if call.excinfo.value else ""
            logger.error(
                f"✗ TEST FAILED | {item.nodeid} | "
                f"{exc_type}: {exc_msg[:300]}"
            )
            # 完整 traceback 写入 DEBUG（文件中有，终端不刷屏）
            logger.debug(
                f"完整异常栈:\n{call.excinfo.exconly()}\n"
                f"{call.excinfo.traceback}"
            )

            # ── A. Allure 附件（升级三逻辑） ──
            ctx = item.funcargs.get("test_context")
            if ctx is not None:
                has_data = (
                    ctx.request_payload is not None
                    or ctx.response_body is not None
                    or ctx.db_snapshots
                )
                if has_data:
                    with allure.step("🔍 失败自动诊断信息 (Auto-Captured)"):
                        _attach_failure_context_to_allure(ctx, item.nodeid)
        else:
            # ── 成功日志（DEBUG 级别，减少正常流程噪音） ──
            logger.debug(f"✓ TEST PASSED | {item.nodeid}")


def pytest_configure(config):
    """
    企业级配置入口：日志系统初始化 + 注册自定义 markers

    日志架构:
      - FileHandler → logs/test_YYYY-MM-DD.log (DEBUG 级别，全量记录)
      - StreamHandler → 控制台 (WARNING 级别，避免终端噪音)
      - 按日期自动分文件，历史日志永久保留用于故障追溯
      - 第三方库 (urllib3/requests) 降噪到 WARNING
    """
    # ── 1. 创建 logs 目录 ──
    logs_dir = Path(__file__).resolve().parent / "logs"
    logs_dir.mkdir(exist_ok=True)

    # ── 2. 按日期生成日志文件名 ──
    today = datetime.now(CST).strftime("%Y-%m-%d")
    log_file = str(logs_dir / f"test_{today}.log")

    # ── 3. 配置根 Logger ──
    root_logger = logging.getLogger()
    log_level = os.environ.get("BANK_LOG_LEVEL", "DEBUG")
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.DEBUG))

    # ── 4. 文件处理器（全量 DEBUG 日志）──
    #     幂等保护：避免 pytest-xdist 或多插件场景下重复添加
    if not any(
        isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", "") == log_file
        for h in root_logger.handlers
    ):
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | [%(name)s] | %(funcName)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        root_logger.addHandler(fh)

        logger.info(f"📝 日志文件: {log_file}")
        logger.info(f"📊 日志级别: {log_level} (可设置 BANK_LOG_LEVEL 环境变量调整)")

    # ── 5. 控制台处理器（WARNING 级别，避免正常流程日志刷屏）──
    console_level = os.environ.get("BANK_CONSOLE_LOG_LEVEL", "WARNING")
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
               for h in root_logger.handlers):
        ch = logging.StreamHandler()
        ch.setLevel(getattr(logging, console_level.upper(), logging.WARNING))
        ch.setFormatter(logging.Formatter(
            "%(levelname)-8s | [%(name)s] | %(message)s"
        ))
        root_logger.addHandler(ch)

    # ── 6. 降噪第三方库 ──
    for noisy in ("urllib3", "urllib3.connectionpool", "requests", "charset_normalizer"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # ── 7. 注册自定义 markers ──
    config.addinivalue_line(
        "markers",
        "smoke: 冒烟测试 — 核心正向流程"
    )
    config.addinivalue_line(
        "markers",
        "regression: 回归测试 — 全量业务规则"
    )
    config.addinivalue_line(
        "markers",
        "negative: 反向测试 — 异常/边界输入"
    )
    config.addinivalue_line(
        "markers",
        "concurrency: 并发测试 — 高并发安全场景"
    )


# ============================================================
# 数据加载工具（供 test_transfer.py 使用）
# ============================================================

def load_yaml_data(file_path: str):
    """
    从 YAML 文件中加载数据驱动测试用例

    返回一个元组 (test_cases, case_ids)：
      - test_cases: list[dict]，每个元素对应一个测试场景
      - case_ids:   list[str]，每个测试用例的 ID，用于 pytest parametrize ids

    【修复说明】
    旧版本只返回 list[dict]，但 YAML 解析结果可能包含非 dict 元素（如嵌套
    列表或标量值），导致 parametrize 注入到 test_transfer 的 tc 参数变成
    tuple/list，进而触发 "tuple indices must be integers or slices, not str"。

    现在函数内部做了严格的类型校验：
      1. 确保顶层 test_cases 是列表
      2. 过滤掉非 dict 元素，只保留合法的测试场景
      3. 同时生成 case_ids，避免调用方重复遍历

    使用方式:
        _test_cases, _param_ids = load_yaml_data(str(DATA_FILE))
        _param_args = [(tc,) for tc in _test_cases]
    """
    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # ---- 防御性提取 ----
    raw_cases = data.get("test_cases", []) if isinstance(data, dict) else []

    # 确保是列表
    if not isinstance(raw_cases, list):
        logger.warning(
            f"YAML 文件中 test_cases 不是列表类型 (实际类型: {type(raw_cases).__name__})，"
            f"将返回空列表"
        )
        return [], []

    # 只保留 dict 类型的元素，过滤掉意外出现的 list/tuple/str 等
    test_cases = []
    case_ids = []
    for idx, tc in enumerate(raw_cases):
        if isinstance(tc, dict):
            test_cases.append(tc)
            # 用例 ID：优先使用 YAML 中的 id 字段，缺失时用序号占位
            tc_id = tc.get("id", f"UNKNOWN_{idx:03d}")
            case_ids.append(tc_id)
        else:
            logger.warning(
                f"跳过非 dict 类型的测试用例 (索引={idx}, 类型={type(tc).__name__}): {tc!r}"
            )

    logger.info(f"成功加载 {len(test_cases)} 条 YAML 测试用例")
    return test_cases, case_ids


# ============================================================
# 自动数据驱动 — YAML 文件发现 + 动态参数化
# ============================================================

# YAML tags → pytest marker 映射表
# 新增 tag 时只需在此表注册，无需修改测试代码
TAG_TO_MARKER = {
    "smoke":             "smoke",
    "positive":          "smoke",
    "regression":        "regression",
    "negative":          "negative",
    "concurrency":       "concurrency",
    "boundary":          "regression",
    "fee":               "regression",
    "input-validation":  "negative",
    "balance-check":     "regression",
    "account-status":    "negative",
    "frozen-account":    "negative",
}


def collect_test_cases(test_module_prefix: str, data_dir: str | None = None) -> tuple:
    """
    自动发现并合并 YAML 测试数据文件（企业级数据驱动核心）

    约定优于配置：
      - test_transfer.py  → 自动加载 data/transfer*.yaml
      - test_auth.py      → 自动加载 data/auth*.yaml
      - test_xxx_yyy.py   → 自动加载 data/xxx_yyy*.yaml

    支持多文件拆分：
      data/
        transfer_smoke.yaml
        transfer_negative.yaml
        transfer_boundary.yaml
      → 全部自动合并执行

    Args:
        test_module_prefix: 从测试模块名推导的文件前缀（如 "transfer"）
        data_dir:           数据目录路径，默认 <项目根>/data/

    Returns:
        (test_cases: list[dict], case_ids: list[str])
        如果未找到匹配的 YAML 文件，返回两个空列表
    """
    if data_dir is None:
        data_dir = str(Path(__file__).resolve().parent / "data")

    pattern = f"{test_module_prefix}*.yaml"
    yaml_files = sorted(glob_module.glob(os.path.join(data_dir, pattern)))

    if not yaml_files:
        logger.warning(
            f"未找到匹配 {pattern} 的 YAML 数据文件，"
            f"请在 {data_dir}/ 目录下创建"
        )
        return [], []

    all_test_cases = []
    all_case_ids = []

    for yf in yaml_files:
        cases, ids = load_yaml_data(yf)
        all_test_cases.extend(cases)
        all_case_ids.extend(ids)

    logger.info(
        f"[数据驱动] 从 {len(yaml_files)} 个 YAML 文件加载了 "
        f"{len(all_test_cases)} 条测试用例 (前缀: {test_module_prefix})"
    )
    return all_test_cases, all_case_ids


def pytest_generate_tests(metafunc):
    """
    Pytest 钩子：为包含 'tc' 参数的测试函数自动注入 YAML 数据

    工作原理：
      1. 检测测试函数签名中是否有 'tc' 参数
      2. 从模块名推导 YAML 文件前缀（test_transfer → transfer）
      3. 调用 collect_test_cases() 加载所有匹配的 YAML 数据
      4. 将 YAML tags 自动映射为 pytest.mark 装饰器
      5. 调用 metafunc.parametrize() 完成参数化注入

    效果：
      - 测试代码中无需手写 @pytest.mark.parametrize
      - 在 data/ 下新增 YAML 文件 → 自动执行
      - 100 个新用例一行 Python 代码都不用改
    """
    if "tc" not in metafunc.fixturenames:
        return

    module_name = metafunc.module.__name__

    # 推导 YAML 文件前缀：test_transfer → transfer
    prefix = module_name
    for strip_word in ("test_", "testcases.", "tests."):
        if prefix.startswith(strip_word):
            prefix = prefix[len(strip_word):]
            break

    if not prefix:
        logger.warning(
            f"无法从模块名 '{module_name}' 推导 YAML 文件前缀，"
            f"将跳过参数化注入"
        )
        return

    test_cases, case_ids = collect_test_cases(prefix)

    if not test_cases:
        # 无匹配数据 → 注入空列表，测试函数不会被调用
        metafunc.parametrize("tc", [], ids=[])
        return

    # 构建 pytest.param 对象：
    #   - Allure feature/story 标签（支撑 Behaviors 视图树状结构）
    #   - YAML tags → pytest marks
    params = []
    for tc, cid in zip(test_cases, case_ids):
        tags = tc.get("tags", [])
        expected = tc.get("expected", {})
        expected_resp_code = expected.get("respCode", "")

        marks = []

        # ── Allure Behaviors 标签 ──
        # 【已注释】此处动态注入会覆盖测试函数上的静态 @allure.feature / @allure.story 装饰器，
        # 导致 Allure 汇总阶段无法正确构建 Behaviors 层级树，进而造成 behaviors.json 缺失。
        # Feature/Story 现由 test_transfer.py 中的静态装饰器 + allure.dynamic.*() 运行时注入接管。
        #
        # marks.append(allure.feature("转账业务"))
        # if expected_resp_code == "000000":
        #     marks.append(allure.story("正向流程"))
        # else:
        #     marks.append(allure.story("异常流程"))

        # ── YAML tags → pytest markers ──
        for tag in tags:
            marker_name = TAG_TO_MARKER.get(tag)
            if marker_name:
                marks.append(getattr(pytest.mark, marker_name))

        params.append(pytest.param(tc, id=cid, marks=marks))

    metafunc.parametrize("tc", params)
