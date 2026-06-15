#  bank-transfer-automation
> **企业级银行转账系统自动化测试与高并发性能验证平台**
[![Bank Transfer CI/CD](https://github.com/xyx433/bank-transfer-automation/actions/workflows/ci-cd.yml/badge.svg)](https://github.com/xyx433/bank-transfer-automation/actions/workflows/ci-cd.yml)

📦 后端源码：本项目的核心 Java 后端代码已独立开源，欢迎查阅：[https://github.com/xyx433/bank-transfer-java]
## 🚀 项目简介
这是一个基于 Python 的银行转账自动化测试与模拟项目。主要实现了账户管理、资金流转以及异常场景（如余额不足、并发冲突）的自动化验证，并包含针对核心接口的高并发性能压测报告。
项目不仅覆盖了 57 个核心功能用例的自动化回归，更深入到底层数据库与架构层面，验证了 **分布式事务、并发幂等、资金安全风控** 等关键特性。同时，结合 JMeter 进行了高并发压力测试，确保系统在极端场景下的数据一致性与稳定性。


## ✨ 核心亮点与测试策略

### 1. 全链路功能覆盖 (Functional Testing)
构建了包含 **57 条** 高价值测试用例的回归套件，覆盖率远超常规业务测试：
- **正向与异常闭环**：覆盖正常转账、余额不足、账户冻结、网络超时等边界场景。
- **长业务流程验证**：模拟跨行转账、多级审批等复杂链路，确保状态机流转正确。
- **接口契约校验**：严格校验入参合法性、响应结构及错误码规范，防止脏数据入库。
  
### 2. 深层架构与数据安全 (Architecture & Security)
跳出纯 UI/API 测试视角，深入验证后端核心机制：
- **数据库事务与锁**：验证 `SELECT FOR UPDATE` 悲观锁机制，确保高并发下余额扣减原子性。
- **并发幂等性设计**：通过重复请求测试，验证防重令牌（Idempotency Key）机制，杜绝资金双倍扣除。
- **权限与安全风控**：验证越权访问拦截、敏感数据脱敏及大额交易风控规则触发逻辑。

### 3. CI/CD 与自动化工程 (Engineering)
- **从 0 到 1 搭建**：独立设计分层测试架构（BasePage -> Service -> TestCase），实现代码高复用。
- **数据驱动 (DDT)**：使用 YAML/SQL 分离测试数据，支持环境隔离与数据自动初始化/清理。
- **持续集成**：集成 GitHub Actions，代码提交即触发自动化回归，实时生成 Allure 可视化报告。
## 🛠️ 技术栈
| 类别 | 技术选型 |
| :--- | :--- |
| **语言** | Python 3.x (Test), Java (Backend) |
| **框架** | Pytest, Requests, Allure |
| **数据库** | MySQL (PyMySQL/SQLAlchemy) |
| **工具** | GitHub Actions, JMeter, Git |

## ⚡ 如何运行
1. **克隆仓库**:
   ```bash
   git clone https://github.com/your-repo-url.git
   cd bank-transfer-automation 
2. 安装依赖: `pip install -r requirements.txt`
3. 配置环境:修改 config.yaml 中的数据库连接与 API 地址。

 4.运行测试:pytest --alluredir=./results/allure-results
allure serve ./results/allure-results

📊 测试结果概览

在最近一次完整的回归测试中，57 个核心用例全部通过 (100% Pass)。报告展示了详细的步骤日志、数据库断言快照及请求响应详情。<img width="1896" height="870" alt="image" src="https://github.com/user-attachments/assets/eda6ec20-1226-4ace-a83b-d675363220e3" />



🔥 高并发性能压测报告

针对核心转账接口进行了高强度的 JMeter 压力测试，旨在验证系统在万级并发下的吞吐能力与资金安全性。

1. 核心性能指标
在持续 30 秒的高压测试中，系统表现极其稳定：
| 指标 | 数值 | 说明 |
| :--- | :--- | :--- |
| 极限吞吐量 (TPS) | 666 | 稳定处理能力 |
| 平均响应时间 (RT) | 2 ms | 极低延迟 |
| 最大响应时间 | 209 ms | 峰值负载表现 |


2. 业务逻辑验证：极致的防超卖机制
⚠️ 特别说明：关于 91% 错误率的深度解读
压测结果中出现的 91% 错误率（18,200 个请求失败）并非系统故障，而是并发锁机制精准生效的完美证明。
场景还原：测试账户初始余额有限（约 92.9 万元）。
机制触发：当高并发请求瞬间耗尽余额后，后续请求被后端代码通过分布式锁/数据库事务精准拦截。
返回结果：系统统一返回 10001 余额不足 的业务异常，拒绝非法交易。
结论：这 91% 的失败意味着 0 数据超卖。在高并发冲击下，系统坚决守住了资金安全底线，未发生一分钱的资产损失。
<img width="1877" height="857" alt="image" src="https://github.com/user-attachments/assets/678f982c-6e6e-4069-86d0-40f3816f67b7" />
🚀 3. 吞吐量稳定性分析
尽管存在大量业务层面的拦截请求，系统的整体处理能力依然保持在高位且曲线平稳。
图表解读：观察 TPS 曲线，系统并未因大量失败请求而崩溃或资源耗尽。
稳定性：黄色点（成功）与红色点（被拦截）交替出现，说明系统负载控制极佳，未发生“雪崩”。
<img width="1647" height="782" alt="image" src="https://github.com/user-attachments/assets/e9d3b494-c2e5-4e7b-9dc9-02d7bd4d75f0" />

⚡ 4. 响应时间分布
系统在处理高并发请求时，展现出了毫秒级的响应速度。绝大多数请求（Median, 90th, 95th percentile）都紧贴着 0ms 基准线。即便是最大值（Max），也仅略高于 200ms，证明了数据库索引优化得当，且没有发生严重的锁等待阻塞。
<img width="1642" height="862" alt="image" src="https://github.com/user-attachments/assets/9d97a1ad-77bb-4afd-b235-4eb61b5ca6de" />


