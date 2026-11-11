import io
import json
import zipfile

import pytest
from django.core.files.base import ContentFile
from openpyxl import load_workbook

from apps.code_monitor.batching import FileChunk
from apps.code_monitor.excel_export import OMISSION_HEADERS, PRIORITY_HEADERS, VULN_HEADERS, write_review_workbook
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
    assert workbook.sheetnames == ["汇总", "测试优先级", "补测用例", "安全测试点"]
    summary = workbook["汇总"]
    assert summary["B2"].value == "'=导入公式"
    assert [cell.value for cell in workbook["测试优先级"][1]] == PRIORITY_HEADERS
    assert workbook["测试优先级"]["C2"].value == "部分实现"
    assert workbook["测试优先级"]["E2"].value == "高"
    assert [cell.value for cell in workbook["补测用例"][1]] == OMISSION_HEADERS
    assert workbook["补测用例"]["D2"].value == "密码错误没有锁定"
    assert workbook["补测用例"]["G2"].value == "账号被锁定"
    assert [cell.value for cell in workbook["安全测试点"][1]] == VULN_HEADERS
    assert workbook["安全测试点"]["C2"].value == "硬编码密钥"
    assert workbook["安全测试点"]["E2"].value == "搜索响应"


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
    assert workbook["补测用例"]["D2"].value == "密码错误没有锁定"
    assert workbook["安全测试点"]["C2"].value == "硬编码密钥"
    assert workbook["测试优先级"]["D2"].value == "围绕缺口加测，并补安全测试"


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
