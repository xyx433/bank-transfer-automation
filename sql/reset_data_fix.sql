-- ============================================================
-- 【终极修复版】测试数据重置脚本 (reset_data_fix.sql)
-- 目的: 解决 GitHub Actions 报错 "单日累计转账限额超限 (10002)"
-- 核心策略: 暴力清空测试账户的所有历史流水，无视时间限制
-- ============================================================

-- 1. 关键修复：清空付款人 & 收款人 的所有交易流水 (核心步骤)
-- 原因: 系统限额统计可能跨天或受时区影响，暴力删除所有记录最安全
-- 注意: 请确保表名 transfer_flow 和字段名 payer_acct/payee_acct 与你的数据库实际一致

DELETE FROM transfer_flow WHERE payer_acct = '6222021234567890';
DELETE FROM transfer_flow WHERE payee_acct = '6228480012345678';

-- 2. 可选：如果还有其他测试账户，一并清空
-- DELETE FROM transfer_flow WHERE payer_acct IN ('6222028888888888', '6222029999999999');

-- 3. 关键修复：强制将限额使用情况归零 (防御性操作)
-- 原因: 防止系统使用缓存字段计数而非查表统计
UPDATE account 
SET daily_used_limit = 0.00, day_amount = 0.00 
WHERE acct_no IN ('6222021234567890', '6228480012345678');

-- 4. 重置账户基础状态 (你原来的逻辑保持不变)
-- 使用 ON DUPLICATE KEY UPDATE 保证幂等性

-- 4.1 付款人：张三 (余额充足，正常状态)
INSERT INTO account 
(acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit, daily_used_limit)
VALUES
('6222021234567890', '张三', '01', '310101199001011234', '102100099996', '中国工商银行北京分行', 1000000.00, 'NORMAL', 1, 200000.00, 50000.00, 0.00)
ON DUPLICATE KEY UPDATE
    balance = 1000000.00,
    account_status = 'NORMAL',
    daily_used_limit = 0.00,
    day_amount = 0.00;

-- 4.2 收款人：李四 (正常状态)
INSERT INTO account 
(acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit, daily_used_limit)
VALUES
('6228480012345678', '李四收款', '01', '411502199001011234', '103100000026', '中国农业银行上海分行', 500000.00, 'NORMAL', 1, 200000.00, 50000.00, 0.00)
ON DUPLICATE KEY UPDATE
    balance = 500000.00,
    account_status = 'NORMAL',
    daily_used_limit = 0.00,
    day_amount = 0.00;

-- 4.3 VIP客户 (刘)
INSERT INTO account 
(acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit, daily_used_limit)
VALUES
('6222028888888888', 'VIP客户刘', '01', '310101198001011234', '102100099996', '中国工商银行北京分行', 2000000.00, 'NORMAL', 5, 500000.00, 100000.00, 0.00)
ON DUPLICATE KEY UPDATE
    balance = 2000000.00,
    account_status = 'NORMAL',
    star_level = 5,
    daily_used_limit = 0.00;

-- 4.4 私银客户 (赵)
INSERT INTO account 
(acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit, daily_used_limit)
VALUES
('6222029999999999', '私银客户赵', '01', '310101197501011234', '102100099996', '中国工商银行北京分行', 5000000.00, 'NORMAL', 7, 1000000.00, 500000.00, 0.00)
ON DUPLICATE KEY UPDATE
    balance = 5000000.00,
    account_status = 'NORMAL',
    star_level = 7,
    daily_used_limit = 0.00;

-- 提交事务
COMMIT;
