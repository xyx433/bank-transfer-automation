-- ============================================================
-- 【强制制造限额超限版】reset_data_fix.sql
-- 目的: 不依赖流水计算，直接修改账户状态，确保存在"单日限额超限"的场景
-- ============================================================

-- 1. 清空流水表 (可选，为了保持环境干净)
DELETE FROM transfer_record WHERE payer_acct_no = '6222021234567890';
DELETE FROM transfer_record WHERE payee_acct_no = '6228480012345678';

-- 2. 【核心修复】强制更新账户表，设置“当日已用额度”等于“单日限额”
-- 假设 acct_no='6222021234567890' (张三) 的 daily_limit 是 200000
-- 我们把 daily_used_limit 强行设为 200000，这样系统会认为额度已经用光了
UPDATE account 
SET 
    daily_used_limit = daily_limit, -- 让已用额度 = 总额度 (即额度已满)
    balance = 1000000.00,           -- 保持余额充足
    account_status = 'NORMAL'
WHERE acct_no = '6222021234567890';

-- 3. 确保收款人状态正常
UPDATE account 
SET 
    daily_used_limit = 0.00,
    balance = 500000.00,
    account_status = 'NORMAL'
WHERE acct_no = '6228480012345678';

COMMIT;
