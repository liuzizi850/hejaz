# TestHub 智能测试管理平台

基于 Django 4.2 与 Vue 3 的测试管理平台，覆盖需求、用例、接口、Web / Android 自动化、性能、监控和 AI 辅助。

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-4.2-green.svg)](https://www.djangoproject.com/)
[![Vue](https://img.shields.io/badge/Vue-3.3-brightgreen.svg)](https://vuejs.org/)
[![License](https://img.shields.io/badge/License-GPL--3.0-blue.svg)](LICENSE)

## 功能

### 需求与用例

- 上传 PDF / Word / TXT，或直接粘贴文本，提取业务需求并生成测试用例
- 需求撰写：保存草稿，并可送交质量审查
- 需求质量审查：从完整性、一致性、可测性给出通过、需修改或拦截
- 用例、套件、执行记录、报告、版本和缺陷的日常管理
- 用例评审：模板、检查清单、多人意见和状态跟踪

### 代码监控

- 登记 Git 地址，或上传 zip
- 扫描任务：从代码中提取 API，导出 Excel
- 检查任务：对照需求原文做代码侧检查，下载报告

### 接口、Web 与 Android 自动化

- API 测试：HTTP / WebSocket、环境变量、断言、历史、定时任务、Allure 报告
- Web UI：Selenium / Playwright，元素库与页面对象，脚本、套件、定时任务和执行记录
- AI 智能模式：用 browser-use 理解页面并执行浏览器任务
- Android：设备与安装包、元素、场景编排、Airtest 执行、WebSocket 进度
- 事件链录制与回放，并打包测试报告

### 质量、性能与运行

- 智能评分器：单条 / 批量评分、量表、知识库和历史记录
- 性能测试：场景、压测执行、实时指标和对比报告
- 监控中心：登录、HTTP、在线率、容器和遥测目标，告警与通知渠道
- 数据工厂：测试数据、编码、JSON、加解密等常用工具
- RAGFlow 助手，以及统一配置里的模型、提示词和 Dify
- MCP：工具调用日志，危险操作需先预览再确认

## 技术栈

| 层 | 主要组件 |
| --- | --- |
| 后端 | Django 4.2、Django REST Framework、drf-spectacular |
| 数据 | MySQL 8.0+、Redis（WebSocket / Celery） |
| 异步 | Celery、Channels + Daphne |
| 自动化 | Selenium、Playwright、browser-use、Airtest、Allure |
| 前端 | Vue 3、Vite、Element Plus、Pinia、Vue Router、ECharts、Monaco Editor、vue-i18n |

## 项目结构

```
testhub_platform/
├── apps/
│   ├── users/                  # 用户
│   ├── projects/               # 项目
│   ├── testcases/              # 手工用例
│   ├── testsuites/             # 套件
│   ├── executions/             # 执行
│   ├── reports/                # 报告
│   ├── defects/                # 缺陷
│   ├── reviews/                # 评审
│   ├── versions/               # 版本
│   ├── requirement_analysis/   # 需求分析、撰写、质量审查、用例生成
│   ├── assistant/              # RAGFlow 助手
│   ├── code_monitor/           # 代码扫描与需求检查
│   ├── api_testing/            # API 测试
│   ├── ui_automation/          # Web UI 自动化
│   ├── app_automation/         # Android 自动化与事件链录制
│   ├── perf_testing/           # 性能测试
│   ├── monitor/                # 监控中心
│   ├── llm_judge/              # 智能评分器
│   ├── mcp/                    # MCP
│   ├── data_factory/           # 数据工厂
│   ├── analytics/              # 行为埋点（可选）
│   └── core/                   # 公共命令、变量解析、通知
├── backend/                    # settings / urls / asgi
├── frontend/                   # Vue 3
├── requirements.txt
└── manage.py
```

## 环境要求

- Python 3.12
- Node.js 18+
- MySQL 8.0+
- Redis 6+（Android 实时进度、Celery、监控调度需要）
- Java 17+（生成 Allure 报告时需要）

## 本地启动

### 后端

```powershell
git clone https://github.com/liuzizi850/hejaz.git
cd hejaz

python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

copy .env.example .env
```

Linux / macOS 将激活命令换成 `source .venv/bin/activate`，复制环境文件用 `cp .env.example .env`。

按 `.env.example` 填写数据库、Redis、邮件和模型密钥。`.env` 已被忽略，不要提交。

```powershell
mysql -u root -p -e "CREATE DATABASE testhub CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
python manage.py migrate
python manage.py createsuperuser
```

可选初始化：

```powershell
python manage.py init_locator_strategies
python manage.py load_component_pack
python manage.py init_judge_rubrics
```

启动：

```powershell
# 仅 HTTP
python manage.py runserver

# 需要 WebSocket（Android 执行进度）时改用 Daphne
daphne -b 0.0.0.0 -p 8000 backend.asgi:application

# 定时任务（API / UI）
python manage.py run_all_scheduled_tasks

# 异步任务（代码监控、APP 自动化等）
celery -A backend worker -l info
```

### 前端

```powershell
cd frontend
npm install
npm run dev
```

生产构建：`npm run build`。

### 访问

- 前端：http://localhost:3000
- 后端：http://localhost:8000
- API 文档：http://localhost:8000/api/docs/
- 管理后台：http://localhost:8000/admin/

### Docker

```bash
./build-and-push.sh
docker-compose up -d
```

镜像仓库、端口和数据库见 `.docker_env`、`docker-compose.yml`。

## 配置

环境变量集中在 `.env`，模板是 `.env.example`。

- 数据库：`DB_NAME`、`DB_USER`、`DB_PASSWORD`、`DB_HOST`、`DB_PORT`
- Redis：`REDIS_URL`
- 邮件：`EMAIL_HOST` 等，供定时任务通知
- 短信：`SMS_PROVIDER` 可选号码认证或短信服务，两套密钥不通用
- 智能评分器：`OPENAI_API_KEY`、`OPENAI_BASE_URL`、`JUDGE_MODEL`；`JUDGE_MOCK=1` 时不调用真实模型
- 需求分析、用例编写、Browser Use 等模型在「统一配置」里维护，可按角色切换并测试连接

生产环境请更换 `SECRET_KEY`，关闭 `DEBUG`，并收紧 `ALLOWED_HOSTS` 与 `CORS_ALLOWED_ORIGINS`。

## 文档

`docs/docs-center/` 里有模块说明：

- [数据工厂使用说明](./docs/docs-center/数据工厂使用说明.md)
- [数据工厂快速开始](./docs/docs-center/数据工厂快速开始.md)
- [数据工厂功能说明](./docs/docs-center/数据工厂功能说明.md)
- [数据工厂 API 接口文档](./docs/docs-center/数据工厂API接口文档.md)
- [UI 自动化测试执行说明](./docs/docs-center/UI自动化测试执行说明.md)
- [UI 自动化测试用户使用手册](./docs/docs-center/UI%20自动化测试用户使用手册.md)
- [WebDriver 驱动管理优化说明](./docs/docs-center/WebDriver驱动管理优化说明.md)
- [用例评审管理功能说明](./docs/docs-center/用例评审管理功能说明.md)
- [I18N 国际化使用说明](./docs/docs-center/I18N国际化使用说明.md)
- [问题排查指南](./docs/docs-center/问题排查指南.md)

## 许可证

GPL-3.0，见 [LICENSE](LICENSE)。
