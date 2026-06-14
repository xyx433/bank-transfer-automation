-- ============================================================
-- 【修复版】测试数据重置脚本
-- 目的: 解决 "单日累计转账限额超限 (10002)" 错误
-- 原理: 1. 清空当日交易流水 2. 强制重置账户状态与限额计数器
-- ============================================================

-- 1. 关键修复：清空当日交易流水表 (核心步骤)
-- 注意：表名可能因库而异，常见的有 transfer_flow, transaction_log, tran_record
-- 如果报错表不存在，请根据实际表名修改
DELETE FROM transfer_flow WHERE payer_acct = '6222021234567890' AND DATE(create_time) = CURDATE();
DELETE FROM transfer_flow WHERE payee_acct = '6228480012345678' AND DATE(create_time) = CURDATE();

-- 2. 关键修复：强制将限额使用情况归零 (如果系统有缓存计数字段)
-- 如果表里有 daily_used_amount, day_transfer_count 这样的字段，强制设为 0
UPDATE account SET daily_used_limit = 0.00, day_amount = 0.00 WHERE acct_no = '6222021234567890';
UPDATE account SET daily_used_limit = 0.00, day_amount = 0.00 WHERE acct_no = '6228480012345678';

-- 3. 重置账户基础状态 (你原来的逻辑)
-- 使用 ON DUPLICATE KEY UPDATE 保证无论插入还是更新，状态都是一致的

-- 3.1 付款人：张三 (余额充足，正常状态)
INSERT INTO account (acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit, daily_used_limit)
VALUES
('6222021234567890', '张三', '01', '310101199001011234', '102100099996', '中国工商银行北京分行', 1000000.00, 'NORMAL', 1, 200000.00, 50000.00, 0.00)
ON DUPLICATE KEY UPDATE
    balance = 1000000.00,
    account_status = 'NORMAL',
    daily_used_limit = 0.00;

-- 3.2 收款人：李四 (正常状态)
INSERT INTO account (acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit, daily_used_limit)
VALUES
('6228480012345678', '李四收款', '01', '411502199001011234', '103100000026', '中国农业银行上海分行', 500000.00, 'NORMAL', 1, 200000.00, 50000.00, 0.00)
ON DUPLICATE KEY UPDATE
    balance = 500000.00,
    account_status = 'NORMAL',
    daily_used_limit = 0.00;

-- 3.3 其他测试账户 (根据需要补充，此处省略部分以节省篇幅，保留你原来的关键账户)
-- ... (保持你原来脚本中对赵六、周八等账户的插入逻辑不变) ...

-- 3.4 VIP客户 (刘)
INSERT INTO account (acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit, daily_used_limit)
VALUES
('6222028888888888', 'VIP客户刘', '01', '310101198001011234', '102100099996', '中国工商银行北京分行', 2000000.00, 'NORMAL', 5, 500000.00, 100000.00, 0.00)
ON DUPLICATE KEY UPDATE
    balance = 2000000.00,
    account_status = 'NORMAL',
    star_level = 5,
    daily_used_limit = 0.00;

-- 3.5 私银客户 (赵)
INSERT INTO account (acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit, daily_used_limit)
VALUES
('6222029999999999', '私银客户赵', '01', '310101197501011234', '102100099996', '中国工商银行北京分行', 5000000.00, 'NORMAL', 7, 1000000.00, 500000.00, 0.00)
ON DUPLICATE KEY UPDATE
    balance = 5000000.00,
    account_status = 'NORMAL',
    star_level = 7,
    daily_used_limit = 0.00;

-- 提交事务
COMMIT;