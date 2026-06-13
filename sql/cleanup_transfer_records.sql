-- ============================================================
-- 测试流水数据清理脚本
-- ============================================================
-- 用途: 每次测试全部结束后，清理本次测试产生的转账流水记录
-- 执行时机: session 级别，全量测试后自动执行
-- 数据库: bank_core (可通过环境变量 BANK_DB_NAME 覆盖)
--
-- 清理策略:
--   删除本次测试运行期间产生的 transfer_record 流水。
--   保留非测试产生的生产数据（通过流水号前缀 PIT 识别测试数据）。
--
-- 重要说明:
--   如果你的 transfer_record 表名或列名不同，请修改下方 SQL。
--   测试流水号的格式为: YYYYMMDD + PIT + 2位渠道码 + 8位序号
--   例如: 20260611PITMB00000001
-- ============================================================

-- 删除本次运行期间由测试产生的转账流水
-- 条件: 受理流水号包含 "PIT" 标记（测试数据特征）
--       且创建时间在最近 24 小时内（双重保险，避免误删历史数据）
DELETE FROM transfer_record
WHERE acp_tran_seq_no LIKE '%PIT%'
   OR core_serial_no LIKE '%PIT%'
   OR tran_seq_no LIKE '%PIT%';

-- 补充清理: 按 idempotency_key 关联的测试记录
-- （UUID 格式的 key 通常为测试生成，保留最近 24h 的）
DELETE FROM transfer_record
WHERE idempotency_key IS NOT NULL
  AND idempotency_key != ''
  AND created_at >= DATE_SUB(NOW(), INTERVAL 1 DAY);