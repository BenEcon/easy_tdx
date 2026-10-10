"""巨潮（cninfo）模块离线测试 —— mock HTTP，零网络依赖。

覆盖：日期转换、orgId 解析（动态表/三段 fallback）、公告解析（含 URL 4 参数、
type 回退、pdf_url）、PDF 下载、分页、错误转换、模块导出。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------


def test_public_exports() -> None:
    """模块应导出 CninfoClient / Announcement / CninfoError。"""
    from easy_tdx import cninfo

    assert hasattr(cninfo, "CninfoClient")
    assert hasattr(cninfo, "Announcement")
    assert hasattr(cninfo, "CninfoError")


def test_announcement_is_frozen_dataclass() -> None:
    """Announcement 应为 frozen dataclass，含全部字段。"""
    from easy_tdx.cninfo import Announcement

    a = Announcement(
        title="t",
        type="ty",
        date="2026-06-14",
        url="http://x",
        code="688017",
        org_id="9900041602",
        announcement_id="abc123",
        announcement_time=1718323200000,
        pdf_url="http://static.cninfo.com.cn/x.PDF",
    )
    assert a.title == "t"
    assert a.type == "ty"
    assert a.date == "2026-06-14"
    assert a.code == "688017"
    assert a.org_id == "9900041602"
    assert a.announcement_id == "abc123"
    assert a.announcement_time == 1718323200000
    assert a.pdf_url == "http://static.cninfo.com.cn/x.PDF"
    # frozen
    with pytest.raises(Exception):
        a.title = "mutated"  # type: ignore[misc]


def test_cninfo_error_is_exception() -> None:
    from easy_tdx.cninfo import CninfoError
    from easy_tdx.exceptions import TdxError

    assert issubclass(CninfoError, Exception)
    # 回归 #1：CninfoError 必须继承 TdxError，保证全局 except TdxError 覆盖
    assert issubclass(CninfoError, TdxError)


def test_build_detail_url_has_four_params() -> None:
    """回归 Bug2：详情页 URL 必须含 4 参数 stockCode/announcementId/orgId/announcementTime。"""
    from easy_tdx.cninfo.models import build_detail_url

    url = build_detail_url("601088", "1225351323", "9900003701", 1780588800000)
    assert "stockCode=601088" in url
    assert "announcementId=1225351323" in url
    assert "orgId=9900003701" in url
    assert "announcementTime=1780588800000" in url


def test_build_pdf_url() -> None:
    """adjunctUrl 应拼成 static.cninfo.com.cn 直链。"""
    from easy_tdx.cninfo.models import build_pdf_url

    assert (
        build_pdf_url("finalpage/2026-06-05/1225351400.PDF")
        == "http://static.cninfo.com.cn/finalpage/2026-06-05/1225351400.PDF"
    )
    assert build_pdf_url("") == ""
    assert build_pdf_url(None) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 日期转换
# ---------------------------------------------------------------------------


def test_ts_to_date_from_millis() -> None:
    """Unix 毫秒整数应转为 YYYY-MM-DD。"""
    from easy_tdx.cninfo.client import _ts_to_date

    assert _ts_to_date(1718323200000)  # 非空字符串，长度 10
    assert len(_ts_to_date(1718323200000)) == 10


def test_ts_to_date_from_string() -> None:
    """字符串输入应取前 10 字符。"""
    from easy_tdx.cninfo.client import _ts_to_date

    assert _ts_to_date("2026-06-14T08:00:00") == "2026-06-14"


def test_ts_to_date_empty() -> None:
    from easy_tdx.cninfo.client import _ts_to_date

    assert _ts_to_date("") == ""
    assert _ts_to_date(None) == ""


# ---------------------------------------------------------------------------
# orgId 解析（动态表 + 三段 fallback）
# ---------------------------------------------------------------------------


@pytest.fixture
def reset_orgid_cache() -> Any:
    """每个测试前后清空 orgId 缓存，保证隔离。"""
    import easy_tdx.cninfo.client as mod

    mod._ORGID_MAP.clear()
    yield
    mod._ORGID_MAP.clear()


def _patch_stock_map(monkeypatch: pytest.MonkeyPatch, mapping: dict[str, str]) -> None:
    """让 _fetch_stock_map 返回给定映射（不触网）。"""
    monkeypatch.setattr(
        "easy_tdx.cninfo.client._http_get_json",
        lambda url, timeout=15.0: {
            "stockList": [{"code": c, "orgId": o} for c, o in mapping.items()]
        },
    )


def test_resolve_orgid_from_dynamic_map(
    monkeypatch: pytest.MonkeyPatch, reset_orgid_cache: Any
) -> None:
    """动态表命中应返回表中 orgId。"""
    from easy_tdx.cninfo import CninfoClient

    _patch_stock_map(monkeypatch, {"688017": "9900041602", "601318": "9900002221"})
    client = CninfoClient()
    assert client._resolve_orgid("688017") == "9900041602"
    assert client._resolve_orgid("601318") == "9900002221"


def test_resolve_orgid_fallback_6_prefix(
    monkeypatch: pytest.MonkeyPatch, reset_orgid_cache: Any
) -> None:
    """动态表无此 code 且 6 开头 → gssh0{code}。"""
    from easy_tdx.cninfo import CninfoClient

    _patch_stock_map(monkeypatch, {})
    client = CninfoClient()
    assert client._resolve_orgid("600519") == "gssh0600519"


def test_resolve_orgid_fallback_8_prefix(
    monkeypatch: pytest.MonkeyPatch, reset_orgid_cache: Any
) -> None:
    """北交所 8/4 开头 → gsbj0{code}。"""
    from easy_tdx.cninfo import CninfoClient

    _patch_stock_map(monkeypatch, {})
    client = CninfoClient()
    assert client._resolve_orgid("830799") == "gsbj0830799"
    assert client._resolve_orgid("430047") == "gsbj0430047"


def test_resolve_orgid_fallback_sz_default(
    monkeypatch: pytest.MonkeyPatch, reset_orgid_cache: Any
) -> None:
    """其他前缀（深圳）→ gssz0{code}。"""
    from easy_tdx.cninfo import CninfoClient

    _patch_stock_map(monkeypatch, {})
    client = CninfoClient()
    assert client._resolve_orgid("000001") == "gssz0000001"


def test_resolve_orgid_empty_map_does_not_cache(
    monkeypatch: pytest.MonkeyPatch, reset_orgid_cache: Any
) -> None:
    """映射表为空时不写入缓存，下次仍会重试（避免永久 fallback）。"""
    import easy_tdx.cninfo.client as mod
    from easy_tdx.cninfo import CninfoClient

    _patch_stock_map(monkeypatch, {})
    client = CninfoClient()
    client._resolve_orgid("600519")
    assert mod._ORGID_MAP == {}


def test_resolve_orgid_fetch_failure_fallback(
    monkeypatch: pytest.MonkeyPatch, reset_orgid_cache: Any
) -> None:
    """映射表拉取异常应 graceful fallback 到硬编码规则，不抛错。"""
    from easy_tdx.cninfo import CninfoClient

    def _boom(url: str, timeout: float = 15.0) -> Any:
        raise OSError("network down")

    monkeypatch.setattr("easy_tdx.cninfo.client._http_get_json", _boom)
    client = CninfoClient()
    # 不抛错，回退 SH 规则
    assert client._resolve_orgid("600519") == "gssh0600519"


def test_resolve_orgid_cache_reused(
    monkeypatch: pytest.MonkeyPatch, reset_orgid_cache: Any
) -> None:
    """第二次调用不应再次拉取映射表（缓存命中）。"""
    call_count = {"n": 0}

    def _fake(url: str, timeout: float = 15.0) -> Any:
        call_count["n"] += 1
        return {"stockList": [{"code": "688017", "orgId": "9900041602"}]}

    monkeypatch.setattr("easy_tdx.cninfo.client._http_get_json", _fake)
    from easy_tdx.cninfo import CninfoClient

    client = CninfoClient()
    client._resolve_orgid("688017")
    client._resolve_orgid("688017")
    assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# 公告查询与解析
# ---------------------------------------------------------------------------


_QUERY_RESPONSE: dict[str, Any] = {
    "announcements": [
        {
            "announcementTitle": "关于召开2025年年度股东大会的通知",
            "announcementTypeName": "股东大会",
            "announcementTime": 1749859200000,
            "announcementId": "abc123",
            "adjunctUrl": "finalpage/2026-06-14/abc123.PDF",
            "adjunctType": "PDF",
        },
        {
            "announcementTitle": "2024年年度报告",
            "announcementTypeName": None,  # Bug1 场景：typeName 为 null
            "announcementTime": 1740614400000,
            "announcementId": "def456",
            "adjunctUrl": "finalpage/2026-02-27/def456.PDF",
            "adjunctType": "PDF",
        },
        {
            "announcementTitle": "无附件公告",
            "announcementTypeName": None,
            "announcementTime": 1740614400000,
            "announcementId": "ghi789",
            "adjunctUrl": "",  # 无 PDF 附件
            "adjunctType": None,
        },
    ],
    "totalAnnouncement": 3,
}


def test_get_announcements_returns_dataframe(
    monkeypatch: pytest.MonkeyPatch, reset_orgid_cache: Any
) -> None:
    """应返回 DataFrame，含全部新字段。"""
    _patch_stock_map(monkeypatch, {"688017": "9900041602"})
    monkeypatch.setattr(
        "easy_tdx.cninfo.client._http_post_form",
        lambda url, payload, timeout=15.0: _QUERY_RESPONSE,
    )
    from easy_tdx.cninfo import CninfoClient

    df = CninfoClient().get_announcements("688017", count=30, page=1)
    assert isinstance(df, pd.DataFrame)
    expected_cols = [
        "title",
        "type",
        "date",
        "url",
        "code",
        "org_id",
        "announcement_id",
        "announcement_time",
        "pdf_url",
    ]
    assert list(df.columns) == expected_cols
    assert len(df) == 3
    # 第一行：正常 typeName
    assert df.iloc[0]["title"] == "关于召开2025年年度股东大会的通知"
    assert df.iloc[0]["type"] == "股东大会"
    assert len(df.iloc[0]["date"]) == 10
    assert df.iloc[0]["pdf_url"].endswith("abc123.PDF")


def test_get_announcements_type_fallback_to_adjunct_type(
    monkeypatch: pytest.MonkeyPatch, reset_orgid_cache: Any
) -> None:
    """回归 Bug1：announcementTypeName 为 null 时回退 adjunctType。"""
    _patch_stock_map(monkeypatch, {"688017": "9900041602"})
    monkeypatch.setattr(
        "easy_tdx.cninfo.client._http_post_form",
        lambda url, payload, timeout=15.0: _QUERY_RESPONSE,
    )
    from easy_tdx.cninfo import CninfoClient

    df = CninfoClient().get_announcements("688017")
    # 第二行 typeName=null 但 adjunctType=PDF → type 应回退为 "PDF"
    assert df.iloc[1]["type"] == "PDF"
    # 第三行 typeName=null 且 adjunctType=null → type 为空字符串（非 nan）
    assert df.iloc[2]["type"] == ""


def test_get_announcements_url_has_four_params(
    monkeypatch: pytest.MonkeyPatch, reset_orgid_cache: Any
) -> None:
    """回归 Bug2：URL 必须含 4 参数才能打开（否则 404）。"""
    _patch_stock_map(monkeypatch, {"688017": "9900041602"})
    monkeypatch.setattr(
        "easy_tdx.cninfo.client._http_post_form",
        lambda url, payload, timeout=15.0: _QUERY_RESPONSE,
    )
    from easy_tdx.cninfo import CninfoClient

    df = CninfoClient().get_announcements("688017")
    url = df.iloc[0]["url"]
    assert "stockCode=688017" in url
    assert "announcementId=abc123" in url
    assert "orgId=9900041602" in url
    assert "announcementTime=" in url


def test_get_announcements_pdf_url(monkeypatch: pytest.MonkeyPatch, reset_orgid_cache: Any) -> None:
    """pdf_url 应为 static.cninfo.com.cn 直链，无附件时为空。"""
    _patch_stock_map(monkeypatch, {"688017": "9900041602"})
    monkeypatch.setattr(
        "easy_tdx.cninfo.client._http_post_form",
        lambda url, payload, timeout=15.0: _QUERY_RESPONSE,
    )
    from easy_tdx.cninfo import CninfoClient

    df = CninfoClient().get_announcements("688017")
    assert df.iloc[0]["pdf_url"] == "http://static.cninfo.com.cn/finalpage/2026-06-14/abc123.PDF"
    assert df.iloc[2]["pdf_url"] == ""  # 无附件


def test_get_announcements_empty(monkeypatch: pytest.MonkeyPatch, reset_orgid_cache: Any) -> None:
    """无公告应返回带列名的空 DataFrame。"""
    _patch_stock_map(monkeypatch, {"688017": "9900041602"})
    monkeypatch.setattr(
        "easy_tdx.cninfo.client._http_post_form",
        lambda url, payload, timeout=15.0: {"announcements": []},
    )
    from easy_tdx.cninfo import CninfoClient

    df = CninfoClient().get_announcements("688017")
    assert isinstance(df, pd.DataFrame)
    assert df.empty
    assert len(df.columns) == 9


def test_get_announcements_missing_key(
    monkeypatch: pytest.MonkeyPatch, reset_orgid_cache: Any
) -> None:
    """响应缺少 announcements 键应视为空结果。"""
    _patch_stock_map(monkeypatch, {"688017": "9900041602"})
    monkeypatch.setattr(
        "easy_tdx.cninfo.client._http_post_form",
        lambda url, payload, timeout=15.0: {"totalAnnouncement": 0},
    )
    from easy_tdx.cninfo import CninfoClient

    df = CninfoClient().get_announcements("688017")
    assert df.empty


def test_get_announcements_request_failure_raises_cninfo_error(
    monkeypatch: pytest.MonkeyPatch, reset_orgid_cache: Any
) -> None:
    """HTTP 异常应转为 CninfoError。"""
    _patch_stock_map(monkeypatch, {"688017": "9900041602"})

    def _boom(url: str, payload: dict[str, str], timeout: float = 15.0) -> Any:
        raise OSError("connection refused")

    monkeypatch.setattr("easy_tdx.cninfo.client._http_post_form", _boom)
    from easy_tdx.cninfo import CninfoClient, CninfoError

    with pytest.raises(CninfoError):
        CninfoClient().get_announcements("688017")


def test_get_announcements_pagination(
    monkeypatch: pytest.MonkeyPatch, reset_orgid_cache: Any
) -> None:
    """count/page 应正确传入 payload。"""
    _patch_stock_map(monkeypatch, {"688017": "9900041602"})
    captured: dict[str, Any] = {}

    def _capture(url: str, payload: dict[str, str], timeout: float = 15.0) -> Any:
        captured.update(payload)
        return {"announcements": []}

    monkeypatch.setattr("easy_tdx.cninfo.client._http_post_form", _capture)
    from easy_tdx.cninfo import CninfoClient

    CninfoClient().get_announcements("688017", count=50, page=3)
    assert captured["pageSize"] == "50"
    assert captured["pageNum"] == "3"
    assert captured["stock"] == "688017,9900041602"
    assert captured["tabName"] == "fulltext"


def test_get_announcements_uses_fallback_orgid(
    monkeypatch: pytest.MonkeyPatch, reset_orgid_cache: Any
) -> None:
    """601xxx 段动态表未命中时用 gssh0 fallback，stock 字段含该 orgId。"""
    _patch_stock_map(monkeypatch, {})  # 空表 → fallback
    captured: dict[str, Any] = {}

    def _capture(url: str, payload: dict[str, str], timeout: float = 15.0) -> Any:
        captured.update(payload)
        return {"announcements": []}

    monkeypatch.setattr("easy_tdx.cninfo.client._http_post_form", _capture)
    from easy_tdx.cninfo import CninfoClient

    CninfoClient().get_announcements("601318")
    assert captured["stock"] == "601318,gssh0601318"


def test_get_announcements_skips_non_dict_items(
    monkeypatch: pytest.MonkeyPatch, reset_orgid_cache: Any
) -> None:
    """announcements 列表中混入非 dict 元素应被跳过。"""
    _patch_stock_map(monkeypatch, {"688017": "9900041602"})
    monkeypatch.setattr(
        "easy_tdx.cninfo.client._http_post_form",
        lambda url, payload, timeout=15.0: {
            "announcements": [
                "not a dict",
                {
                    "announcementTitle": "ok",
                    "announcementTime": 1749859200000,
                    "announcementId": "x",
                    "adjunctUrl": "",
                },
            ]
        },
    )
    from easy_tdx.cninfo import CninfoClient

    df = CninfoClient().get_announcements("688017")
    assert len(df) == 1
    assert df.iloc[0]["title"] == "ok"


def test_get_announcements_response_not_dict(
    monkeypatch: pytest.MonkeyPatch, reset_orgid_cache: Any
) -> None:
    """响应非 dict（如 list）应视为空结果，不抛错。"""
    _patch_stock_map(monkeypatch, {"688017": "9900041602"})
    monkeypatch.setattr(
        "easy_tdx.cninfo.client._http_post_form",
        lambda url, payload, timeout=15.0: ["unexpected", "list"],
    )
    from easy_tdx.cninfo import CninfoClient

    df = CninfoClient().get_announcements("688017")
    assert df.empty


def test_get_announcements_malformed_timestamp_wrapped_as_cninfo_error(
    monkeypatch: pytest.MonkeyPatch, reset_orgid_cache: Any
) -> None:
    """announcementTime 畸形（导致 fromtimestamp 溢出）应转 CninfoError，不裸抛。

    回归 #2：修复前 _ts_to_date 在 try 块外，畸形时间戳会抛 OverflowError/
    ValueError 裸异常；修复后整个解析路径统一转 CninfoError。
    """
    _patch_stock_map(monkeypatch, {"688017": "9900041602"})
    monkeypatch.setattr(
        "easy_tdx.cninfo.client._http_post_form",
        lambda url, payload, timeout=15.0: {
            "announcements": [
                {"announcementTitle": "x", "announcementTime": 10**30, "announcementId": "y"}
            ]
        },
    )
    from easy_tdx.cninfo import CninfoClient, CninfoError

    with pytest.raises(CninfoError):
        CninfoClient().get_announcements("688017")


# ---------------------------------------------------------------------------
# PDF 下载
# ---------------------------------------------------------------------------


def _make_anno(**overrides: Any) -> Any:
    """构造测试用 Announcement（默认有 pdf_url）。"""
    from easy_tdx.cninfo import Announcement

    defaults: dict[str, Any] = {
        "title": "测试公告",
        "type": "PDF",
        "date": "2026-06-14",
        "url": "http://x",
        "code": "688017",
        "org_id": "9900041602",
        "announcement_id": "abc123",
        "announcement_time": 1718323200000,
        "pdf_url": "http://static.cninfo.com.cn/x.PDF",
    }
    defaults.update(overrides)
    return Announcement(**defaults)


def test_download_pdf_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """download_pdf 应写入文件并返回绝对路径。"""
    from easy_tdx.cninfo import CninfoClient

    pdf_bytes = b"%PDF-1.4\nfake pdf content"

    class _FakeResp:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self) -> _FakeResp:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    def _fake_urlopen(req: Any, timeout: float = 15.0) -> _FakeResp:
        return _FakeResp(pdf_bytes)

    import easy_tdx.cninfo.client as mod

    monkeypatch.setattr(mod.urlrequest, "urlopen", _fake_urlopen)
    anno = _make_anno()
    path = CninfoClient().download_pdf(anno, dest_dir=tmp_path)
    assert Path(path).exists()
    assert Path(path).read_bytes() == pdf_bytes
    # 默认文件名格式：{date}_{announcement_id}.PDF
    assert "abc123" in Path(path).name
    assert Path(path).name.endswith(".PDF")


def test_download_pdf_custom_filename(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """自定义 filename 应被使用。"""
    from easy_tdx.cninfo import CninfoClient

    class _FakeResp:
        def read(self) -> bytes:
            return b"%PDF-1.4"

        def __enter__(self) -> _FakeResp:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    import easy_tdx.cninfo.client as mod

    monkeypatch.setattr(mod.urlrequest, "urlopen", lambda req, timeout=15.0: _FakeResp())
    path = CninfoClient().download_pdf(_make_anno(), dest_dir=tmp_path, filename="custom.pdf")
    assert Path(path).name == "custom.pdf"


def test_download_pdf_no_attachment_raises() -> None:
    """pdf_url 为空应抛 CninfoError，不触网。"""
    from easy_tdx.cninfo import CninfoClient, CninfoError

    anno = _make_anno(pdf_url="")
    with pytest.raises(CninfoError):
        CninfoClient().download_pdf(anno)


def test_download_pdf_creates_dest_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """目标目录不存在应自动创建。"""
    from easy_tdx.cninfo import CninfoClient

    class _FakeResp:
        def read(self) -> bytes:
            return b"%PDF-1.4"

        def __enter__(self) -> _FakeResp:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    import easy_tdx.cninfo.client as mod

    monkeypatch.setattr(mod.urlrequest, "urlopen", lambda req, timeout=15.0: _FakeResp())
    nested = tmp_path / "a" / "b" / "c"
    path = CninfoClient().download_pdf(_make_anno(), dest_dir=nested)
    assert Path(path).exists()
    assert nested.is_dir()


def test_download_pdf_accepts_series(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """download_pdf 应兼容 pd.Series（DataFrame.iloc[i] 的返回类型）。"""
    from easy_tdx.cninfo import CninfoClient

    class _FakeResp:
        def read(self) -> bytes:
            return b"%PDF-1.4"

        def __enter__(self) -> _FakeResp:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    import easy_tdx.cninfo.client as mod

    monkeypatch.setattr(mod.urlrequest, "urlopen", lambda req, timeout=15.0: _FakeResp())
    # 模拟 DataFrame 的一行
    row = pd.Series(
        {
            "title": "t",
            "type": "PDF",
            "date": "2026-06-14",
            "url": "http://x",
            "code": "688017",
            "org_id": "9900041602",
            "announcement_id": "abc",
            "announcement_time": 1718323200000,
            "pdf_url": "http://static.cninfo.com.cn/x.PDF",
        }
    )
    path = CninfoClient().download_pdf(row, dest_dir=tmp_path)
    assert Path(path).exists()


def test_download_pdf_network_failure_wrapped(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """下载网络失败应转 CninfoError。"""
    from easy_tdx.cninfo import CninfoClient, CninfoError

    def _boom(req: Any, timeout: float = 15.0) -> Any:
        raise OSError("connection reset")

    import easy_tdx.cninfo.client as mod

    monkeypatch.setattr(mod.urlrequest, "urlopen", _boom)
    with pytest.raises(CninfoError):
        CninfoClient().download_pdf(_make_anno(), dest_dir=tmp_path)


# ---------------------------------------------------------------------------
# urllib helper 烟雾测试（不触网，仅验证 JSON 解码路径）
# ---------------------------------------------------------------------------


def test_http_post_form_urlencoded_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """_http_post_form 应以 application/x-www-form-urlencoded 发送。"""
    import easy_tdx.cninfo.client as mod

    captured: dict[str, Any] = {}

    class _FakeResp:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self) -> _FakeResp:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    def _fake_urlopen(req: Any, timeout: float = 15.0) -> _FakeResp:
        captured["data"] = req.data
        captured["headers"] = {k: v for k, v in req.header_items()}
        captured["method"] = req.get_method()
        return _FakeResp(json.dumps({"ok": True}).encode("utf-8"))

    monkeypatch.setattr(mod.urlrequest, "urlopen", _fake_urlopen)
    result = mod._http_post_form("https://example.com/api", {"pageNum": "2", "pageSize": "30"})
    assert result == {"ok": True}
    assert b"pageNum=2" in captured["data"]
    assert b"pageSize=30" in captured["data"]
    assert captured["method"] == "POST"
    headers = {k.lower(): v for k, v in captured["headers"].items()}
    assert "cninfo.com.cn" in headers.get("referer", "")
    assert "x-www-form-urlencoded" in headers.get("content-type", "")


def test_http_get_json_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """_http_get_json 应携带 User-Agent。"""
    import easy_tdx.cninfo.client as mod

    captured: dict[str, Any] = {}

    class _FakeResp:
        def read(self) -> bytes:
            return json.dumps({"ok": 1}).encode("utf-8")

        def __enter__(self) -> _FakeResp:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    def _fake_urlopen(req: Any, timeout: float = 15.0) -> _FakeResp:
        captured["headers"] = {k: v for k, v in req.header_items()}
        return _FakeResp()

    monkeypatch.setattr(mod.urlrequest, "urlopen", _fake_urlopen)
    assert mod._http_get_json("https://example.com/x.json") == {"ok": 1}
    headers = {k.lower(): v for k, v in captured["headers"].items()}
    assert "user-agent" in headers
