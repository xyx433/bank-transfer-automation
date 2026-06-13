-- ============================================================
-- 测试账户状态重置脚本
-- ============================================================
-- 用途: 每次测试开始前，将所有测试账户重置到已知初始状态
-- 执行时机: session 级别，全量测试前自动执行
-- 数据库: bank_core (可通过环境变量 BANK_DB_NAME 覆盖)
--
-- 重要说明:
--   如果你的 account 表列名不同，请修改下方 SQL 中的列名。
--   本脚本使用 INSERT ... ON DUPLICATE KEY UPDATE 保证幂等性：
--   无论执行多少次，结果一致。
-- ============================================================

-- ──────────────────────────────────────────────
-- 1. 张三 — 正常一类户，余额充足
--    用于大多数正向转账测试
-- ──────────────────────────────────────────────
INSERT INTO account (acct_no, acct_name, balance, status, account_type)
VALUES ('6222021234567890', '张三', 1000000.00, 'NORMAL', 'I')
ON DUPLICATE KEY UPDATE
    acct_name = '张三',
    balance = 1000000.00,
    status = 'NORMAL',
    account_type = 'I';

-- ──────────────────────────────────────────────
-- 2. 李四收款 — 跨行收款账户（农行），正常状态
--    用于跨行转账正向测试
-- ──────────────────────────────────────────────
INSERT INTO account (acct_no, acct_name, balance, status, account_type)
VALUES ('6228480012345678', '李四收款', 500000.00, 'NORMAL', 'I')
ON DUPLICATE KEY UPDATE
    acct_name = '李四收款',
    balance = 500000.00,
    status = 'NORMAL',
    account_type = 'I';

-- ──────────────────────────────────────────────
-- 3. 赵六 — 低余额账户（仅 100 元）
--    用于余额不足类反向测试
-- ──────────────────────────────────────────────
INSERT INTO account (acct_no, acct_name, balance, status, account_type)
VALUES ('6222021234567893', '赵六', 100.00, 'NORMAL', 'I')
ON DUPLICATE KEY UPDATE
    acct_name = '赵六',
    balance = 100.00,
    status = 'NORMAL',
    account_type = 'I';

-- ──────────────────────────────────────────────
-- 4. 周八 — 司法冻结账户
--    用于账户状态异常类反向测试
-- ──────────────────────────────────────────────
INSERT INTO account (acct_no, acct_name, balance, status, account_type)
VALUES ('6222021234567895', '周八', 100000.00, 'FROZEN', 'I')
ON DUPLICATE KEY UPDATE
    acct_name = '周八',
    balance = 100000.00,
    status = 'FROZEN',
    account_type = 'I';

-- ──────────────────────────────────────────────
-- 5. 睡眠户测试卡
--    用于睡眠户/销户状态反向测试
-- ──────────────────────────────────────────────
INSERT INTO account (acct_no, acct_name, balance, status, account_type)
VALUES ('6222029999998888', '睡眠户测试用户', 50000.00, 'SLEEP', 'I')
ON DUPLICATE KEY UPDATE
    acct_name = '睡眠户测试用户',
    balance = 50000.00,
    status = 'SLEEP',
    account_type = 'I';

-- ──────────────────────────────────────────────
-- 6. 黑名单收款账户
--    用于反诈/风控类反向测试
-- ──────────────────────────────────────────────
INSERT INTO account (acct_no, acct_name, balance, status, account_type)
VALUES ('6228481111111111', '黑名单账户', 10000.00, 'NORMAL', 'I')
ON DUPLICATE KEY UPDATE
    acct_name = '黑名单账户',
    balance = 10000.00,
    status = 'NORMAL',
    account_type = 'I';