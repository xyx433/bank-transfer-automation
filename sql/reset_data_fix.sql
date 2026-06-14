-- ============================================================
-- 【终极防时差版】测试数据重置脚本 (reset_data_fix.sql)
-- 策略: 暴力清空法 + 宽字段名匹配
-- ============================================================

-- 1. 关键修复：暴力清空测试账户的所有交易流水 (无视时间限制，解决时差问题)
-- 原因: 服务器时区(UTC)与本地时区(CST)不一致导致 CURDATE() 匹配失败

-- 尝试匹配常见的字段名变体 (acct_no, account_no, payer_acct 等)
DELETE FROM transfer_flow 
WHERE 
    -- 付款人字段常见变体
    (payer_acct_no = '6222021234567890' OR payer_acct = '6222021234567890' OR from_acct = '6222021234567890')
    OR 
    -- 收款人字段常见变体
    (payee_acct_no = '6228480012345678' OR payee_acct = '6228480012345678' OR to_acct = '6228480012345678');

-- 2. 防御性更新：强制归零账户表中的统计字段
-- 即使流水删了，有些系统会缓存计数在账户表里
UPDATE account 
SET 
    daily_used_limit = 0.00, 
    day_transfer_count = 0,
    update_time = NOW() 
WHERE 
    acct_no IN ('6222021234567890', '6228480012345678');

-- 3. 重置账户基础数据 (保持不变)
-- 使用 ON DUPLICATE KEY UPDATE 确保数据一致

INSERT INTO account (
    acct_no, acct_name, id_type, id_no, bank_code, bank_name, 
    balance, account_status, star_level, daily_limit, single_limit
) VALUES 
-- 付款人：张三 (余额充足)
('6222021234567890', '张三', '01', '310101199001011234', '102100099996', '中国工商银行北京分行', 
 1000000.00, 'NORMAL', 1, 200000.00, 50000.00),

-- 收款人：李四
('6228480012345678', '李四收款', '01', '411502199001011234', '103100000026', '中国农业银行上海分行', 
 500000.00, 'NORMAL', 1, 200000.00, 50000.00),

-- VIP客户 (刘)
('6222028888888888', 'VIP客户刘', '01', '310101198001011234', '102100099996', '中国工商银行北京分行', 
 2000000.00, 'NORMAL', 5, 500000.00, 100000.00),

-- 私银客户 (赵)
('6222029999999999', '私银客户赵', '01', '310101197501011234', '102100099996', '中国工商银行北京分行', 
 5000000.00, 'NORMAL', 7, 1000000.00, 500000.00)
ON DUPLICATE KEY UPDATE
    balance = VALUES(balance),
    account_status = VALUES(account_status),
    daily_used_limit = 0.00,
    update_time = NOW();

-- 4. 提交事务
COMMIT;
