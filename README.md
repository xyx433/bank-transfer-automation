#  bank-transfer-automation
[![Bank Transfer CI/CD](https://github.com/xyx433/bank-transfer-automation/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/xyx433/bank-transfer-automation/actions/workflows/ci-cd.yml)

## 🚀 项目简介
这是一个基于 Python 的银行转账自动化测试/模拟项目。主要实现了账户管理、资金流转以及异常场景（如余额不足、并发冲突）的自动化验证。

## ✨ 核心亮点
- **CI/CD 集成**：配置了 GitHub Actions，每次提交代码自动运行单元测试，确保逻辑正确。
- **数据驱动**：使用 SQL 脚本初始化测试环境，保证测试数据的纯净和可重复性。
- **异常处理**：重点覆盖了转账失败、网络超时等边界情况的处理逻辑。

## 🛠️ 技术栈
- **语言**: Python 3.x
- **数据库**: MySQL 
- **工具**: Pytest, GitHub Actions

## ⚡ 如何运行
. 克隆仓库: `git clone ...`
. 安装依赖: `pip install -r requirements.txt`
. 运行测试: `pytest`
### 📈 测试报告示例
以下是最近一次构建生成的 Allure 可视化报告，展示了 18 个核心用例全部通过：<img width="1882" height="862" alt="屏幕截图 2026-06-14 091600" src="https://github.com/user-attachments/assets/3ff71c57-1da7-4659-894e-9fe771e4bd45" />


🏦 银行转账系统 - 高并发性能压测报告
本项目针对核心转账接口进行了高强度的 JMeter 压力测试，旨在验证系统在万级并发下的吞吐能力与资金安全性。
📊 1. 核心性能指标概览
在持续 30 秒的高压测试中，系统表现极其稳定，展现了极高的处理效率：
极限吞吐量 (TPS)：稳定维持在 666 TPS
平均响应时间 (RT)：2 ms
最大响应时间：209 ms
🛡️ 2. 业务逻辑验证：极致的防超卖机制
⚠️ 特别说明：为何出现 91% 的错误率？
下图中的红色区域并非系统故障，而是并发锁机制生效的完美证明。
由于测试账户余额有限（约 92.9 万元），当高并发请求瞬间耗尽余额后，后续的 18,200 个请求被后端代码精准拦截，返回了 10001 余额不足 的业务异常。
这 91% 的 FAIL 意味着：
✅ 在高并发狂轰滥炸下，数据库事务与锁机制 100% 准确执行。
✅ 坚决守住了底线，未发生任何一分钱的数据超卖现象。
<img width="1877" height="857" alt="image" src="https://github.com/user-attachments/assets/678f982c-6e6e-4069-86d0-40f3816f67b7" />
🚀 3. 吞吐量稳定性分析
尽管有大量业务拦截请求，系统的整体处理能力依然保持在高位且平稳。
图表解读：从下方的 TPS 曲线可以看出，系统并没有因为大量的失败请求而发生“雪崩”或资源耗尽。黄色点代表成功处理的请求，红色点代表被拦截的请求，两者并行不悖，说明系统负载控制极佳。
<img width="1647" height="782" alt="image" src="https://github.com/user-attachments/assets/e9d3b494-c2e5-4e7b-9dc9-02d7bd4d75f0" />
⚡ 4. 响应时间分布
系统在处理高并发请求时，展现出了毫秒级的响应速度。
图表解读：绝大多数请求（Median, 90th, 95th percentile）都紧贴着 0ms 基准线。即便是最大值（Max），也仅略高于 200ms。这证明了数据库索引优化得当，且没有发生严重的锁等待阻塞。
<img width="1642" height="862" alt="image" src="https://github.com/user-attachments/assets/9d97a1ad-77bb-4afd-b235-4eb61b5ca6de" />


