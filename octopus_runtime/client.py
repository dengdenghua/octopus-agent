"""octopus-runtime · registry 客户端(httpx + pydantic,**永不 import 产品 runtime**)。

实现 capability-plane.md §B 的「拉取 → 验签」半边:列目录 / 下载单资产 / sha256 校验。
读/解析层无任何 runtime 依赖,可被任何产品 vendor。
"""

from __future__ import annotations

import hashlib
import re

import httpx
from pydantic import BaseModel

DEFAULT_BASE = "https://api.octoapk.com"
_API = "/api/v1/registry/assets"
_SHA256_RE = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")


def _sha256_expected(value: str | None, *, label: str) -> str | None:
    if not value:
        return None
    m = _SHA256_RE.fullmatch(value.strip())
    if not m:
        raise ValueError(f"invalid sha256 checksum for {label}: {value!r}")
    return m.group(1).lower()


class AssetContent(BaseModel):
    ref: str | None = None
    checksum: str | None = None  # "sha256:<hex>"


class BundleRef(BaseModel):
    """full-bundle:技能整目录 tar.gz(带 scripts/refs/requirements)。None = body-only 足够。"""

    ref: str | None = None
    checksum: str | None = None  # "sha256:<hex>"
    size: int | None = None


class RegistryAsset(BaseModel):
    """registry 信封(轻量元数据;list 不含 body)。"""

    id: str = ""  # "skill/<slug>"
    type: str = ""
    kind: str = ""  # data | code(安全分水岭:data 可落地,code 只作广告)
    version: str = ""
    name: str = ""
    description: str = ""
    category: str | None = None
    tags: list[str] | None = None
    mode: str | None = None  # inject | tool
    platforms: list[str] | None = None
    deps: list[str] | None = None
    content: AssetContent | None = None
    bundle: BundleRef | None = None  # 有则该技能是整目录分发(full-bundle)

    @property
    def slug(self) -> str:
        return self.id.rsplit("/", 1)[-1]


class AssetPayload(RegistryAsset):
    """download 返回:信封 + 正文 body。"""

    body: str = ""


class RegistryClient:
    """瘦客户端:列目录 + 下载(内容寻址、验签)。无状态、无 runtime 依赖。"""

    def __init__(self, base_url: str = DEFAULT_BASE, timeout: float = 30.0) -> None:
        self.base = base_url.rstrip("/")
        self._timeout = timeout

    def list_assets(self, type_: str | None = None) -> list[RegistryAsset]:
        params = {"type": type_} if type_ else {}
        r = httpx.get(self.base + _API, params=params, timeout=self._timeout)
        r.raise_for_status()
        data = r.json().get("data", []) or []
        return [RegistryAsset.model_validate(a) for a in data]

    def list_skills(self) -> list[RegistryAsset]:
        return self.list_assets(type_="skill")

    def fetch(self, asset_id: str) -> AssetPayload:
        """下载单资产(信封 + body)并**校验 sha256 checksum**。失败抛异常。"""
        r = httpx.get(f"{self.base}{_API}/{asset_id}/download", timeout=self._timeout)
        r.raise_for_status()
        d = r.json().get("data") or {}
        payload = AssetPayload.model_validate(d)
        self._verify(payload)
        return payload

    def fetch_bundle(self, asset_id: str) -> bytes:
        """下载技能 **full-bundle**(整目录 tar.gz)并校验 sha256(X-Checksum-Sha256 头)。
        无 bundle → httpx 抛 404。"""
        r = httpx.get(f"{self.base}{_API}/{asset_id}/bundle", timeout=self._timeout)
        r.raise_for_status()
        data = r.content
        expected = _sha256_expected(r.headers.get("X-Checksum-Sha256"), label=asset_id)
        if expected:
            actual = hashlib.sha256(data).hexdigest()
            if actual != expected:
                raise ValueError(f"bundle checksum mismatch for {asset_id}: expected {expected} got {actual}")
        return data

    @staticmethod
    def _verify(p: AssetPayload) -> None:
        expected = _sha256_expected(p.content.checksum if p.content else None, label=p.id)
        if expected:
            actual = hashlib.sha256(p.body.encode("utf-8")).hexdigest()
            if actual != expected:
                raise ValueError(f"checksum mismatch for {p.id}: expected {expected} got {actual}")
