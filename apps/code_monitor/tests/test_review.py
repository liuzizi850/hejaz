import io
import json
import zipfile

import pytest
from django.core.files.base import ContentFile
from openpyxl import load_workbook

from apps.code_monitor.batching import FileChunk
from apps.code_monitor.excel_export import FILTER_HEADERS, write_review_workbook
from apps.code_monitor.models import ScanTask
from apps.code_monitor.pipeline import execute_scan
from apps.code_monitor.review import (
    Finding,
    Omission,
    ReviewReport,
    Vulnerability,
    build_index,
    normalize_finding,
    retrieve_snippets,
    review_repository,
    split_checkpoints,
)
from apps.requirement_analysis.models import AIModelConfig
from apps.users.models import User


def test_retrieve_matches_chinese_requirement_to_code(tmp_path):
    (tmp_path / "login.py").write_text(
        "def login_by_phone(phone, password):\n    return phone\n",
        encoding="utf-8",
    )
    (tmp_path / "order.py").write_text("def create_order():\n    return 1\n", encoding="utf-8")
    snippets = retrieve_snippets(build_index(tmp_path), "用户可以用手机号登录")
    assert snippets
    assert snippets[0].source_file == "login.py"


def test_missing_code_does_not_ask_the_model(tmp_path, monkeypatch):
    (tmp_path / "order.py").write_text("def create_order():\n    return 1\n", encoding="utf-8")

    def fake_call(config, system, user):
        assert "拆成检查点" in system
        return json.dumps([{"text": "支持火星基地供电", "checkable": True}])

    monkeypatch.setattr("apps.code_monitor.review.call_model", fake_call)
    report = review_repository(None, tmp_path, "支持火星基地供电")
    assert report.findings[0].verdict == "missing"
    assert report.findings[0].evidence_note == "未检索到相关代码"
    assert report.findings[0].advice == "先跟开发确认未实现"
    assert report.findings[0].priority == "中"


def test_backend_code_skips_page_appearance(tmp_path, monkeypatch):
    (tmp_path / "Wallet.java").write_text("class Wallet { int balance; }\n", encoding="utf-8")

    def fake_call(config, system, user):
        if "拆成检查点" in system:
            assert "当前只有后端代码" in user
            return json.dumps([
                {"text": "冻结余额用红字显示", "checkable": True, "reason": ""},
                {"text": "点击跳转到冻结列表", "checkable": True, "reason": ""},
                {"text": "购票时校验可用余额", "checkable": True, "reason": ""},
            ])
        assert "校验可用余额" in user
        assert "红字" not in user
        return json.dumps({
            "verdict": "partial",
            "evidence_file": "Wallet.java",
            "evidence_note": "有余额字段",
            "omissions": [
                {"kind": "validation", "gap": "未校验余额是否足够", "steps": "购票", "evidence_file": "Wallet.java"},
                {"kind": "validation", "gap": "余额没有用红字显示", "steps": "打开首页", "evidence_file": "Wallet.java"},
            ],
        })

    monkeypatch.setattr("apps.code_monitor.review.call_model", fake_call)
    report = review_repository(None, tmp_path, "余额用红字显示，点击可跳转，购票要校验余额")
    assert report.findings[0].verdict == "uncheckable"
    assert report.findings[1].verdict == "uncheckable"
    assert [item.gap for item in report.findings[2].omissions] == ["未校验余额是否足够"]


def test_frontend_code_still_checks_appearance(tmp_path, monkeypatch):
    (tmp_path / "Home.vue").write_text("<template><p class=\"red\">余额</p></template>\n", encoding="utf-8")

    def fake_call(config, system, user):
        if "拆成检查点" in system:
            assert "当前只有后端代码" not in user
            return json.dumps([{"text": "冻结余额用红字显示", "checkable": True, "reason": ""}])
        assert "红字" in user
        return json.dumps({"verdict": "missing", "evidence_note": "没有样式"})

    monkeypatch.setattr("apps.code_monitor.review.call_model", fake_call)
    finding = review_repository(None, tmp_path, "冻结余额用红字显示").findings[0]
    assert finding.verdict == "missing"


def test_uncheckable_point_skips_code(tmp_path, monkeypatch):
    (tmp_path / "login.py").write_text("def login():\n    return 1\n", encoding="utf-8")

    def fake_call(config, system, user):
        return json.dumps([{"text": "体验要好", "checkable": False, "reason": "主观描述"}])

    monkeypatch.setattr("apps.code_monitor.review.call_model", fake_call)
    report = review_repository(None, tmp_path, "体验要好")
    finding = report.findings[0]
    assert finding.verdict == "uncheckable"
    assert finding.advice == "需求太笼统，需要产品补充后再测"
    assert finding.evidence_note == "主观描述"


def test_split_keeps_every_checkpoint(monkeypatch):
    items = [{"text": f"功能点{index}可以登录", "checkable": True} for index in range(21)]
    monkeypatch.setattr("apps.code_monitor.review.call_model", lambda *args: json.dumps(items))
    kept, truncated = split_checkpoints(None, "需求")
    assert len(kept) == 21
    assert [item["text"] for item in kept] == [f"功能点{index}可以登录" for index in range(21)]
    assert truncated is False


def test_conclusion_without_evidence_is_downgraded():
    finding = normalize_finding(
        1,
        "用户可以用手机号登录",
        {
            "verdict": "implemented",
            "evidence_file": "other.py",
            "omissions": [{"kind": "branch", "gap": "没有锁定", "evidence_file": "other.py"}],
        },
        ["login.py"],
        [FileChunk("login.py", "def login():\n    return 1\n")],
    )
    assert finding.verdict == "missing"
    assert finding.omissions == []
    assert finding.evidence_note == "未检索到能支撑结论的代码"


def test_omission_without_existing_code_is_dropped():
    finding = normalize_finding(
        1,
        "用户可以用手机号登录",
        {
            "verdict": "partial",
            "evidence_file": "login.py",
            "evidence_note": "有登录入口",
            "omissions": [{
                "kind": "branch",
                "gap": "没有锁定",
                "steps": ["输入错误密码", "再试一次"],
                "evidence_file": "missing.py",
            }],
        },
        ["login.py"],
        [FileChunk("login.py", "def login():\n    return 1\n")],
    )
    assert finding.verdict == "partial"
    assert finding.omissions == []
    assert finding.priority == "高"
    assert finding.advice == "围绕缺口加测"


def test_regex_secret_is_kept_once():
    snippet = FileChunk("login.py", 'api_key = "abcd1234efgh"\n')
    finding = normalize_finding(
        1,
        "用户可以用手机号登录",
        {
            "verdict": "implemented",
            "evidence_file": "login.py",
            "evidence_note": "有登录入口",
            "vulnerabilities": [{
                "kind": "secret",
                "risk": "密钥写在代码里",
                "how_to_test": "搜索接口响应",
                "expected": "不应出现密钥",
                "evidence_file": "login.py",
            }],
        },
        ["login.py"],
        [snippet],
    )
    assert len(finding.vulnerabilities) == 1
    assert finding.vulnerabilities[0].risk == "密钥写在代码里"
    assert finding.priority == "高"
    assert finding.advice == "主流程抽一条即可，并补安全测试"


def test_activity_requirement_retrieves_event_code(tmp_path):
    (tmp_path / "EventService.java").write_text(
        "class EventService {\n  void createEvent() { save(event); }\n}\n",
        encoding="utf-8",
    )
    (tmp_path / "Wallet.java").write_text("class Wallet { int balance; }\n", encoding="utf-8")
    snippets = retrieve_snippets(build_index(tmp_path), "活动创建成功后，生成唯一活动 ID 并落库存储")
    assert [item.source_file for item in snippets] == ["EventService.java"]


def test_review_workbook_is_for_testers():
    report = ReviewReport(
        requirement="=导入公式",
        findings=[
            Finding(
                number=1,
                text="用户可以用手机号登录",
                verdict="partial",
                advice="围绕缺口加测",
                priority="高",
                evidence_path="login.py",
                evidence_note="有登录入口",
                omissions=[Omission("branch", "密码错误没有锁定", "已有账号", "连续输入错误密码", "账号被锁定", "login.py")],
                vulnerabilities=[Vulnerability("secret", "密钥写在代码里", "搜索响应", "不应出现密钥", "login.py")],
            )
        ],
    )
    workbook = load_workbook(io.BytesIO(write_review_workbook(report)))
    assert workbook.sheetnames == ["测试过滤"]
    sheet = workbook["测试过滤"]
    assert [cell.value for cell in sheet[1]] == FILTER_HEADERS
    assert [cell.value for cell in sheet[2]] == ["用户可以用手机号登录", "连续输入错误密码", "密码错误没有锁定"]
    assert [cell.value for cell in sheet[3]] == ["用户可以用手机号登录", "做该需求相关操作时", "密钥写在代码里"]
    escaped = write_review_workbook(ReviewReport(
        requirement="=导入公式",
        findings=[Finding(
            1, "=导入公式", "partial", "", "中", "a.py", "有入口",
            omissions=[Omission("branch", "=缺口", "", "提交", "", "a.py")],
        )],
    ))
    escaped_sheet = load_workbook(io.BytesIO(escaped))["测试过滤"]
    assert escaped_sheet["A2"].value == "'=导入公式"
    assert escaped_sheet["C2"].value == "'=缺口"
    unseen = write_review_workbook(ReviewReport(
        requirement="创建活动",
        findings=[Finding(1, "活动创建后生成唯一活动ID", "missing", "", "中", "", "给定代码片段中未出现活动创建逻辑")],
    ))
    unseen_sheet = load_workbook(io.BytesIO(unseen))["测试过滤"]
    assert unseen_sheet.max_row == 2
    assert unseen_sheet["C2"].value == "没有看出明显遗漏"


@pytest.mark.django_db
def test_requirement_scan_writes_tester_report(monkeypatch):
    user = User.objects.create_user(username="review-scan", password="pass123456")
    config = AIModelConfig.objects.create(
        name="检查模型",
        model_type="other",
        role="writer",
        base_url="https://example.com/v1",
        model_name="fake",
        created_by=user,
        is_active=True,
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "login.py",
            'def login_by_phone(phone, password):\n    api_key = "abcd1234efgh"\n    return True\n',
        )
    task = ScanTask.objects.create(
        source_type=ScanTask.SOURCE_ZIP,
        task_type=ScanTask.TASK_REQUIREMENT_REVIEW,
        requirement_text="用户可以用手机号登录",
        model_config=config,
        created_by=user,
    )
    task.archive.save("repo.zip", ContentFile(buffer.getvalue()), save=True)

    def fake_call(config, system, user_text):
        if "拆成检查点" in system:
            return json.dumps([{"text": "用户可以用手机号登录", "checkable": True, "reason": ""}])
        assert "login.py" in user_text
        return json.dumps({
            "verdict": "partial",
            "evidence_file": "login.py",
            "evidence_note": "已有手机号登录入口",
            "omissions": [{
                "kind": "branch",
                "gap": "密码错误没有锁定",
                "precondition": "已有账号",
                "steps": "连续输入错误密码",
                "expected": "账号被锁定",
                "evidence_file": "login.py",
            }],
            "vulnerabilities": [],
        })

    monkeypatch.setattr("apps.code_monitor.review.call_model", fake_call)
    execute_scan(task.id, token="super-secret-token")
    task.refresh_from_db()
    assert task.status == ScanTask.STATUS_SUCCEEDED
    assert task.progress == 100
    assert f"requirement-review-{task.id}" in task.result_file.name
    assert task.result_file.name.endswith(".xlsx")
    assert not task.archive
    assert "super-secret-token" not in task.error_message
    workbook = load_workbook(io.BytesIO(task.result_file.read()))
    sheet = workbook["测试过滤"]
    assert [cell.value for cell in sheet[2]] == ["用户可以用手机号登录", "连续输入错误密码", "密码错误没有锁定"]
    assert sheet["C3"].value == "代码中存在硬编码密钥"


@pytest.mark.django_db
def test_requirement_scan_without_source_fails():
    user = User.objects.create_user(username="review-empty", password="pass123456")
    config = AIModelConfig.objects.create(
        name="检查模型",
        model_type="other",
        role="writer",
        base_url="https://example.com/v1",
        model_name="fake",
        created_by=user,
        is_active=True,
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "hello")
    task = ScanTask.objects.create(
        source_type=ScanTask.SOURCE_ZIP,
        task_type=ScanTask.TASK_REQUIREMENT_REVIEW,
        requirement_text="用户可以用手机号登录",
        model_config=config,
        created_by=user,
    )
    task.archive.save("empty.zip", ContentFile(buffer.getvalue()), save=True)
    execute_scan(task.id)
    task.refresh_from_db()
    assert task.status == ScanTask.STATUS_FAILED
    assert task.error_message == "没有找到可检查的源代码"
    assert not task.result_file


def test_i18n_question_is_checked_in_code_even_if_model_skips_it(tmp_path, monkeypatch):
    zh = tmp_path / "src" / "locales" / "zh-cn"
    en = tmp_path / "src" / "locales" / "en"
    zh.mkdir(parents=True)
    en.mkdir(parents=True)
    (zh / "nav.js").write_text("export default { login: '登录', logout: '退出' }\n", encoding="utf-8")
    (en / "nav.js").write_text("export default { login: 'Login' }\n", encoding="utf-8")
    (tmp_path / "src" / "locales" / "index.js").write_text("import { createI18n } from 'vue-i18n'\n", encoding="utf-8")
    views = tmp_path / "src" / "views"
    views.mkdir()
    (views / "Login.vue").write_text("<template><div>请登录</div></template>\n", encoding="utf-8")

    def fake_call(config, system, user):
        assert "拆成检查点" in system
        return json.dumps([{"text": "是否做了国际化", "checkable": False, "reason": "没有具体行为"}])

    monkeypatch.setattr("apps.code_monitor.review.call_model", fake_call)
    report = review_repository(None, tmp_path, "是否做了国际化")
    finding = report.findings[0]
    assert finding.verdict == "partial"
    assert finding.priority == "高"
    gaps = " ".join(item.gap for item in finding.omissions)
    assert "logout" in gaps
    assert "Login.vue" in gaps
    assert "请登录" in gaps


def test_i18n_question_reports_missing_when_code_has_no_i18n(tmp_path, monkeypatch):
    (tmp_path / "order.py").write_text("def create_order():\n    return 1\n", encoding="utf-8")

    def fake_call(config, system, user):
        return json.dumps([{"text": "是否做了国际化", "checkable": False, "reason": "太笼统"}])

    monkeypatch.setattr("apps.code_monitor.review.call_model", fake_call)
    finding = review_repository(None, tmp_path, "是否做了国际化").findings[0]
    assert finding.verdict == "missing"
    assert "未检索到国际化实现" in finding.evidence_note
    assert finding.advice == "先跟开发确认未实现"


def test_complete_i18n_is_implemented(tmp_path, monkeypatch):
    zh = tmp_path / "src" / "locales" / "zh-cn"
    en = tmp_path / "src" / "locales" / "en"
    zh.mkdir(parents=True)
    en.mkdir(parents=True)
    (zh / "nav.js").write_text("export default { login: '登录' }\n", encoding="utf-8")
    (en / "nav.js").write_text("export default { login: 'Login' }\n", encoding="utf-8")
    views = tmp_path / "src" / "views"
    views.mkdir()
    (views / "Login.vue").write_text("<template><div>{{ $t('login') }}</div></template>\n", encoding="utf-8")
    monkeypatch.setattr(
        "apps.code_monitor.review.call_model",
        lambda *args: json.dumps([{"text": "是否做了国际化", "checkable": False, "reason": ""}]),
    )
    finding = review_repository(None, tmp_path, "是否做了国际化").findings[0]
    assert finding.verdict == "implemented"
    assert finding.omissions == []
    assert finding.priority == "低"


def test_no_checkpoints_scans_whole_code_for_bugs(tmp_path, monkeypatch):
    (tmp_path / "app.py").write_text(
        "def run(cmd):\n    eval(cmd)\n    try:\n        risky()\n    except Exception:\n        pass\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("apps.code_monitor.review.call_model", lambda *args: "[]")
    finding = review_repository(None, tmp_path, "这代码有什么漏洞没有").findings[0]
    assert finding.verdict == "partial"
    assert any(item.kind == "eval" for item in finding.vulnerabilities)
    assert any("忽略" in item.gap for item in finding.omissions)
    assert finding.advice == "按补测用例和安全测试点逐条验证"


def test_clean_code_scan_reports_no_obvious_bug(tmp_path, monkeypatch):
    (tmp_path / "app.py").write_text("def add(left, right):\n    return left + right\n", encoding="utf-8")
    monkeypatch.setattr("apps.code_monitor.review.call_model", lambda *args: "[]")
    finding = review_repository(None, tmp_path, "这代码有什么漏洞没有").findings[0]
    assert finding.verdict == "implemented"
    assert finding.vulnerabilities == []
    assert finding.omissions == []
    assert "未发现明显漏洞和缺陷" in finding.advice
