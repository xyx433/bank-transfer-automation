-- ============================================================
-- 测试账户状态重置脚本 (基于真实表结构生成)
-- ============================================================
-- 用途: 每次测试开始前，将所有测试账户重置到已知初始状态
-- 执行时机: session 级别，全量测试前自动执行
-- 说明: 本脚本使用 INSERT ... ON DUPLICATE KEY UPDATE 保证幂等性
-- ============================================================

-- 1. 张三 — 正常一类户，余额充足
INSERT INTO account (acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit)
VALUES ('6222021234567890', '张三', '01', '310101199001011234', '102100099996', '中国工商银行北京分行', 1000000.00, 'NORMAL', 1, 200000.00, 50000.00)
ON DUPLICATE KEY UPDATE
    acct_name = '张三',
    balance = 1000000.00,
    account_status = 'NORMAL';

-- 2. 李四收款 — 跨行收款账户（农行），正常状态
INSERT INTO account (acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit)
VALUES ('6228480012345678', '李四收款', '01', '411502199001011234', '103100000026', '中国农业银行上海分行', 500000.00, 'NORMAL', 1, 200000.00, 50000.00)
ON DUPLICATE KEY UPDATE
    acct_name = '李四收款',
    balance = 500000.00,
    account_status = 'NORMAL';

-- 3. 赵六 — 低余额账户（仅 100 元）
INSERT INTO account (acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit)
VALUES ('6222021234567893', '赵六', '01', '310101199001011235', '102100099996', '中国工商银行北京分行', 100.00, 'NORMAL', 1, 200000.00, 50000.00)
ON DUPLICATE KEY UPDATE
    acct_name = '赵六',
    balance = 100.00,
    account_status = 'NORMAL';

-- 4. 周八 — 司法冻结账户
INSERT INTO account (acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit)
VALUES ('6222021234567895', '周八', '01', '310101199001011236', '102100099996', '中国工商银行北京分行', 100000.00, 'FROZEN', 1, 200000.00, 50000.00)
ON DUPLICATE KEY UPDATE
    acct_name = '周八',
    balance = 100000.00,
    account_status = 'FROZEN';

-- 5. 睡眠户测试卡
INSERT INTO account (acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit)
VALUES ('6222029999998888', '睡眠户测试用户', '01', '310101199001011237', '102100099996', '中国工商银行北京分行', 50000.00, 'SLEEP', 1, 200000.00, 50000.00)
ON DUPLICATE KEY UPDATE
    acct_name = '睡眠户测试用户',
    balance = 50000.00,
    account_status = 'SLEEP';

-- 6. 黑名单收款账户
-- 修改点：将 account_status 改为风控拦截对应的状态
INSERT INTO account (acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit)
VALUES ('6228481111111111', '黑名单账户', '01', '411502199001011238', '103100000026', '中国农业银行上海分行', 10000.00, 'RISK_BLACKLIST', 1, 200000.00, 50000.00)
ON DUPLICATE KEY UPDATE
    acct_name = '黑名单账户',
    balance = 10000.00,
    account_status = 'RISK_BLACKLIST'; -- 确保这里和上面一致

-- 7. 部分冻结账户（吴九）：冻结金额95000，可用余额仅5000
INSERT INTO account (acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit)
VALUES ('6222021234567896', '吴九', '01', '310101199001011239', '102100099996', '中国工商银行北京分行', 100000.00, 'PARTIAL_FROZEN', 1, 200000.00, 50000.00)
ON DUPLICATE KEY UPDATE
    acct_name = '吴九',
    balance = 100000.00,
    account_status = 'PARTIAL_FROZEN';

-- 8. 挂失账户（郑十）
INSERT INTO account (acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit)
VALUES ('6222021234567897', '郑十', '01', '310101199001011240', '102100099996', '中国工商银行北京分行', 50000.00, 'LOST', 1, 200000.00, 50000.00)
ON DUPLICATE KEY UPDATE
    acct_name = '郑十',
    balance = 50000.00,
    account_status = 'LOST';

-- 9. 已销户账户（王十一）
INSERT INTO account (acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit)
VALUES ('6222021234567898', '王十一', '01', '310101199001011241', '102100099996', '中国工商银行北京分行', 0.00, 'CLOSED', 1, 200000.00, 50000.00)
ON DUPLICATE KEY UPDATE
    acct_name = '王十一',
    balance = 0.00,
    account_status = 'CLOSED';

-- 10. 交易限制/反洗钱风险管控账户（陈十二）
INSERT INTO account (acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit)
VALUES ('6222021234567899', '陈十二', '01', '310101199001011242', '102100099996', '中国工商银行北京分行', 50000.00, 'RESTRICTED', 1, 200000.00, 50000.00)
ON DUPLICATE KEY UPDATE
    acct_name = '陈十二',
    balance = 50000.00,
    account_status = 'RESTRICTED';

-- 11. VIP客户（star_level=5，手续费减免50%）
INSERT INTO account (acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit)
VALUES ('6222028888888888', 'VIP客户刘', '01', '310101198001011234', '102100099996', '中国工商银行北京分行', 2000000.00, 'NORMAL', 5, 500000.00, 100000.00)
ON DUPLICATE KEY UPDATE
    acct_name = 'VIP客户刘',
    balance = 2000000.00,
    account_status = 'NORMAL',
    star_level = 5;

-- 12. 私银客户（star_level=7，手续费全免）
INSERT INTO account (acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit)
VALUES ('6222029999999999', '私银客户赵', '01', '310101197501011234', '102100099996', '中国工商银行北京分行', 5000000.00, 'NORMAL', 7, 1000000.00, 500000.00)
ON DUPLICATE KEY UPDATE
    acct_name = '私银客户赵',
    balance = 5000000.00,
    account_status = 'NORMAL',
    star_level = 7;

-- 13. 观察名单收款账户（频繁小额、投诉率>3%，单日收款限额降至5000）
INSERT INTO account (acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit)
VALUES ('6228482222222222', '观察名单账户', '01', '411502199001011239', '103100000026', '中国农业银行上海分行', 20000.00, 'NORMAL', 1, 5000.00, 5000.00)
ON DUPLICATE KEY UPDATE
    acct_name = '观察名单账户',
    balance = 20000.00,
    account_status = 'NORMAL';

-- 14. 贷记卡收款账户（信用卡BIN，入金额外风控）
INSERT INTO account (acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit)
VALUES ('5327450001234567', '贷记卡收款测试', '01', '411502199001011240', '103100000026', '中国农业银行上海分行', 0.00, 'NORMAL', 1, 200000.00, 50000.00)
ON DUPLICATE KEY UPDATE
    acct_name = '贷记卡收款测试',
    balance = 0.00,
    account_status = 'NORMAL';