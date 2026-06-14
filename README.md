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

