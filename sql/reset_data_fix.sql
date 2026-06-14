-- ============================================================
-- 【最终修正版】测试数据重置脚本 (基于真实表结构)
-- 核心修复：
-- 1. 修正表名为 transfer_record
-- 2. 增加对 daily_limit_stat 表的清理（这是解决限额报错的关键）
-- ============================================================

-- 1. 清空转账流水记录 (防止历史数据干扰统计)
-- 注意：这里使用了正确的表名 transfer_record
DELETE FROM transfer_record WHERE payer_acct_no = '6222021234567890';
DELETE FROM transfer_record WHERE payee_acct_no = '6228480012345678';

-- 2. 【关键步骤】重置日限额统计表
-- 很多时候系统判断限额是查这张表，而不是实时计算流水
-- 如果该表存在，必须将 used_amount 归零
UPDATE daily_limit_stat
SET used_amount = 0.00, update_time = NOW()
WHERE acct_no IN ('6222021234567890', '6228480012345678');

-- 3. 重置账户基础信息 (保持你原有的幂等性逻辑)
-- 假设 account 表中包含 daily_used_limit 字段，一并更新以防万一
INSERT INTO account (acct_no, acct_name, id_type, id_no, bank_code, bank_name, balance, account_status, star_level, daily_limit, single_limit, daily_used_limit)
VALUES
('6222021234567890', '张三', '01', '310101199001011234', '102100099996', '中国工商银行北京分行', 1000000.00, 'NORMAL', 1, 200000.00, 50000.00, 0.00),
('6228480012345678', '李四收款', '01', '411502199001011234', '103100000026', '中国农业银行上海分行', 500000.00, 'NORMAL', 1, 200000.00, 50000.00, 0.00)
ON DUPLICATE KEY UPDATE
    balance = VALUES(balance),
    account_status = VALUES(account_status),
    daily_used_limit = 0.00; -- 强制归零

COMMIT;
