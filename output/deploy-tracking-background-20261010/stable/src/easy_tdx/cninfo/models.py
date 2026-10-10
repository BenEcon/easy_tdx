"""巨潮资讯网（cninfo）数据模型。"""

from __future__ import annotations

from dataclasses import dataclass

from easy_tdx.exceptions import TdxError

# PDF 附件直链前缀（adjunctUrl 拼此 base 即真实 PDF 地址）
_PDF_BASE = "http://static.cninfo.com.cn/"


@dataclass(frozen=True)
class Announcement:
    """单条公告记录。

    巨潮公告检索接口返回的标准化结构。

    Attributes:
        title: 公告标题。
        type: 公告类型（优先 ``announcementTypeName``，缺失时回退 ``adjunctType``
            如 "PDF"，再缺失给空字符串 — cninfo 对很多公告不填 typeName）。
        date: 公告日期 ``YYYY-MM-DD``。
        url: 公告详情页 URL（含 stockCode/announcementId/orgId/announcementTime 四参数）。
        code: 6 位股票代码。
        org_id: 巨潮 orgId（详情页 URL 参数）。
        announcement_id: 巨潮公告 ID（详情页 URL 参数 + PDF 文件名构成）。
        announcement_time: 原始 Unix 毫秒时间戳（详情页 URL 参数）。
        pdf_url: PDF 附件直链（``adjunctUrl`` 拼接 ``static.cninfo.com.cn``），
            无附件时为空字符串。
    """

    title: str
    type: str
    date: str  # YYYY-MM-DD
    url: str
    code: str
    org_id: str
    announcement_id: str
    announcement_time: int
    pdf_url: str


def build_detail_url(code: str, announcement_id: str, org_id: str, announcement_time: int) -> str:
    """构造公告详情页 URL（4 参数缺一不可，否则 404）。"""
    return (
        "https://www.cninfo.com.cn/new/disclosure/detail?"
        f"stockCode={code}&announcementId={announcement_id}"
        f"&orgId={org_id}&announcementTime={announcement_time}"
    )


def build_pdf_url(adjunct_url: str) -> str:
    """``adjunctUrl``（如 finalpage/2026-06-05/xxx.PDF）拼成完整 PDF 直链。

    无附件（adjunctUrl 为空）返回空字符串。
    """
    if not adjunct_url:
        return ""
    return f"{_PDF_BASE}{adjunct_url}"


class CninfoError(TdxError):
    """巨潮数据请求或解析失败。"""
